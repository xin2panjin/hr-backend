"""系统角色授予、撤销和部门范围管理服务。"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from models.iam import AuditLogModel, ScopeTypeEnum, UserRoleModel, UserRoleScopeModel
from models.user import DepartmentStatus, UserModel, UserStatus
from iam.permissions import RoleCode
from repository.iam_repo import IamRepo
from repository.user_repo import DepartmentRepo


class RoleAssignmentValidationError(ValueError):
    """角色或范围不符合固定 RBAC 规则。"""


class RoleAssignmentConflict(Exception):
    """角色状态不允许当前操作。"""


class RoleAssignmentService:
    """集中处理角色生命周期，避免 Router 直接操作关联表。"""

    def __init__(self, session):
        self.session = session
        self.iam_repo = IamRepo(session)
        self.department_repo = DepartmentRepo(session)

    async def validate_role_scope(
        self,
        *,
        role_code: str,
        department_ids: list[str],
        reason: str | None,
    ) -> list[str]:
        """供邀请等同样需要校验角色范围的入口复用。"""

        return await self._validate_scope(
            role_code=role_code,
            department_ids=department_ids,
            reason=reason,
        )

    async def grant_role(
        self,
        *,
        user: UserModel,
        role_code: str,
        department_ids: list[str],
        expires_at: datetime | None,
        reason: str | None,
        actor_id: str,
    ) -> UserRoleModel:
        expires_at = self._normalize_datetime(expires_at)
        if user.status != UserStatus.ACTIVE:
            raise RoleAssignmentValidationError("只能向状态正常的用户授予角色")
        if expires_at and expires_at <= datetime.now():
            raise RoleAssignmentValidationError("角色失效时间必须晚于当前时间")

        role = await self.iam_repo.get_role_by_code(role_code)
        if not role:
            raise RoleAssignmentValidationError("角色代码不存在")
        normalized_department_ids = await self._validate_scope(
            role_code=role.code,
            department_ids=department_ids,
            reason=reason,
        )

        existing = await self.iam_repo.get_unrevoked_user_role(
            user_id=user.id,
            role_id=role.id,
        )
        if existing and (existing.expires_at is None or existing.expires_at > datetime.now()):
            raise RoleAssignmentConflict("用户已拥有该有效角色")

        if existing:
            before_data = self._role_snapshot(existing)
            existing.assigned_by = actor_id
            existing.assigned_at = datetime.now()
            existing.expires_at = expires_at
            self._replace_department_scopes(existing, normalized_department_ids)
            user_role = existing
            action = "user_role.regrant"
        else:
            user_role = UserRoleModel(
                user_id=user.id,
                role_id=role.id,
                assigned_by=actor_id,
                assigned_at=datetime.now(),
                expires_at=expires_at,
            )
            user_role.role = role
            self._replace_department_scopes(user_role, normalized_department_ids)
            self.session.add(user_role)
            # BaseModel 的主键在 flush 时生成，确保审计快照含有稳定的授予 ID。
            await self.session.flush()
            before_data = None
            action = "user_role.grant"

        user.authz_version += 1
        self._audit(
            actor_id=actor_id,
            action=action,
            target_id=user.id,
            before_data=before_data,
            after_data=self._role_snapshot(user_role, reason=reason),
        )
        return user_role

    async def revoke_role(
        self,
        *,
        user_role: UserRoleModel,
        actor_id: str,
        reason: str,
        user: UserModel,
    ) -> UserRoleModel:
        if user_role.revoked_at:
            raise RoleAssignmentConflict("角色已撤销")
        if not reason.strip():
            raise RoleAssignmentValidationError("撤销角色必须填写原因")

        before_data = self._role_snapshot(user_role)
        user_role.revoked_at = datetime.now()
        user_role.revoke_reason = reason.strip()
        user.authz_version += 1
        self._audit(
            actor_id=actor_id,
            action="user_role.revoke",
            target_id=user.id,
            before_data=before_data,
            after_data=self._role_snapshot(user_role),
        )
        return user_role

    async def replace_department_scopes(
        self,
        *,
        user_role: UserRoleModel,
        user: UserModel,
        department_ids: list[str],
        actor_id: str,
        reason: str | None,
    ) -> UserRoleModel:
        if user_role.revoked_at:
            raise RoleAssignmentConflict("已撤销角色不能修改范围")
        if user_role.expires_at and user_role.expires_at <= datetime.now():
            raise RoleAssignmentConflict("已失效角色不能修改范围，请重新授予")

        normalized_department_ids = await self._validate_scope(
            role_code=user_role.role.code,
            department_ids=department_ids,
            reason=reason,
        )
        before_data = self._role_snapshot(user_role)
        self._replace_department_scopes(user_role, normalized_department_ids)
        user.authz_version += 1
        self._audit(
            actor_id=actor_id,
            action="user_role.scope.replace",
            target_id=user.id,
            before_data=before_data,
            after_data=self._role_snapshot(user_role, reason=reason),
        )
        return user_role

    async def _validate_scope(
        self,
        *,
        role_code: str,
        department_ids: list[str],
        reason: str | None,
    ) -> list[str]:
        department_ids = list(dict.fromkeys(department_ids))
        if role_code == RoleCode.SYSTEM_ADMIN.value and not (reason or "").strip():
            raise RoleAssignmentValidationError("授予系统管理员角色必须填写授权原因")
        if role_code == RoleCode.RECRUITER.value and not department_ids:
            raise RoleAssignmentValidationError("招聘专员必须配置至少一个负责部门")
        if role_code != RoleCode.RECRUITER.value and department_ids:
            raise RoleAssignmentValidationError("当前角色不支持部门范围配置")

        for department_id in department_ids:
            department = await self.department_repo.get_by_id(department_id)
            if not department or department.status != DepartmentStatus.ACTIVE:
                raise RoleAssignmentValidationError("部门范围包含不存在或已归档的部门")
        return department_ids

    @staticmethod
    def _replace_department_scopes(
        user_role: UserRoleModel,
        department_ids: list[str],
    ) -> None:
        user_role.scopes = [
            UserRoleScopeModel(
                scope_type=ScopeTypeEnum.DEPARTMENT,
                department_id=department_id,
            )
            for department_id in department_ids
        ]

    def _audit(
        self,
        *,
        actor_id: str,
        action: str,
        target_id: str,
        before_data: dict[str, Any] | None,
        after_data: dict[str, Any] | None,
    ) -> None:
        self.session.add(
            AuditLogModel(
                actor_id=actor_id,
                action=action,
                target_type="user_role",
                target_id=target_id,
                before_data=before_data,
                after_data=after_data,
            )
        )

    @staticmethod
    def _normalize_datetime(value: datetime | None) -> datetime | None:
        """统一存储 UTC 的无时区时间，兼容 API 传入的 ISO 8601 时区。"""

        if value and value.tzinfo:
            return value.astimezone(timezone.utc).replace(tzinfo=None)
        return value

    @staticmethod
    def _role_snapshot(
        user_role: UserRoleModel,
        *,
        reason: str | None = None,
    ) -> dict[str, Any]:
        return {
            "user_role_id": user_role.id,
            "role_code": user_role.role.code,
            "expires_at": user_role.expires_at.isoformat() if user_role.expires_at else None,
            "revoked_at": user_role.revoked_at.isoformat() if user_role.revoked_at else None,
            "revoke_reason": user_role.revoke_reason,
            "department_ids": sorted(
                str(scope.department_id) for scope in user_role.scopes if scope.department_id
            ),
            "reason": reason,
        }
