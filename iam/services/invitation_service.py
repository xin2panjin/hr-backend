"""持久化邀请的创建与注册核销服务。"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from models.iam import AuditLogModel, InvitationModel
from models.user import DepartmentStatus, UserModel
from repository.iam_repo import IamRepo
from repository.user_repo import DepartmentRepo, UserRepo
from settings import settings
from iam.services.password_policy import validate_password

from .role_assignment_service import RoleAssignmentService


class InvitationValidationError(ValueError):
    """邀请参数或注册状态不符合规则。"""


class InvitationConflict(Exception):
    """同一邮箱已存在未处理邀请等冲突。"""


class InvitationService:
    def __init__(self, session):
        self.session = session
        self.iam_repo = IamRepo(session)
        self.user_repo = UserRepo(session)
        self.department_repo = DepartmentRepo(session)
        self.role_assignment_service = RoleAssignmentService(session)

    async def create_invitation(
        self,
        *,
        email: str,
        username: str,
        department_id: str,
        role_code: str,
        department_scope_ids: list[str],
        expires_at: datetime | None,
        reason: str | None,
        actor_id: str,
    ) -> tuple[InvitationModel, str]:
        email = self.normalize_email(email)
        username = self.normalize_username(username)
        if not username:
            raise InvitationValidationError("用户名不能为空")
        if await self.user_repo.get_by_email(email):
            raise InvitationConflict("该邮箱已注册")
        if await self.user_repo.get_by_username(username):
            raise InvitationConflict("该用户名已被使用")
        unresolved_invitation = await self.iam_repo.get_unresolved_invitation_by_email(email)
        if unresolved_invitation:
            if unresolved_invitation.expires_at > datetime.now():
                raise InvitationConflict("该邮箱已有未使用邀请，请先取消或等待其过期")
            # 部分唯一索引不包含时间条件，重新邀请前需显式核销旧过期记录。
            unresolved_invitation.cancelled_at = datetime.now()
            unresolved_invitation.cancelled_by = actor_id
            await self.session.flush()

        unresolved_username_invitation = await self.iam_repo.get_unresolved_invitation_by_username(username)
        if unresolved_username_invitation and unresolved_username_invitation.id != getattr(unresolved_invitation, "id", None):
            raise InvitationConflict("该用户名已有待完成邀请")

        department = await self.department_repo.get_by_id(department_id)
        if not department or department.status != DepartmentStatus.ACTIVE:
            raise InvitationValidationError("邀请的主所属部门不存在或已归档")
        role = await self.iam_repo.get_role_by_code(role_code)
        if not role:
            raise InvitationValidationError("角色代码不存在")
        scope_ids = await self.role_assignment_service.validate_role_scope(
            role_code=role.code,
            department_ids=department_scope_ids,
            reason=reason,
        )
        expires_at = self._normalize_datetime(expires_at) or datetime.now() + timedelta(
            seconds=settings.INVITE_CODE_EXPIRE_SECONDS
        )
        if expires_at <= datetime.now():
            raise InvitationValidationError("邀请失效时间必须晚于当前时间")

        invite_code = secrets.token_urlsafe(24)
        invitation = InvitationModel(
            email=email,
            username=username,
            department_id=department_id,
            role_id=role.id,
            department_scope_ids=scope_ids,
            invite_code_hash=self.hash_invite_code(email, invite_code),
            expires_at=expires_at,
            invited_by=actor_id,
            reason=reason.strip() if reason else None,
        )
        invitation.role = role
        self.session.add(invitation)
        await self.session.flush()
        if unresolved_invitation:
            self._audit(
                actor_id=actor_id,
                action="invitation.expire.cancel",
                target_id=unresolved_invitation.id,
                after_data=self._snapshot(unresolved_invitation),
            )
        self._audit(
            actor_id=actor_id,
            action="invitation.create",
            target_id=invitation.id,
            after_data=self._snapshot(invitation),
        )
        return invitation, invite_code

    async def register_from_invitation(
        self,
        *,
        email: str,
        invite_code: str,
        user_data: dict[str, Any],
    ) -> UserModel:
        """核销持久化邀请并原子创建用户与初始角色。"""

        email = self.normalize_email(email)
        invitation = await self.iam_repo.get_invitation_for_registration(
            email=email,
            invite_code_hash=self.hash_invite_code(email, invite_code),
        )
        if not invitation:
            if await self.iam_repo.has_invitation_for_email(email):
                raise InvitationValidationError("邀请不存在、已失效或已使用")
            raise InvitationValidationError("邀请不存在或已失效")
        if await self.user_repo.get_by_email(email):
            raise InvitationConflict("该邮箱已注册")

        invitation_username = self.normalize_username(invitation.username)
        requested_username = self.normalize_username(str(user_data["username"]))
        if invitation_username != requested_username:
            raise InvitationValidationError("用户名与邀请指定的账号不一致")
        if await self.user_repo.get_by_username(invitation_username):
            raise InvitationConflict("该用户名已被使用")

        validate_password(
            str(user_data["password"]),
            username=str(user_data["username"]),
            email=email,
        )

        department = await self.department_repo.get_by_id(invitation.department_id)
        if not department or department.status != DepartmentStatus.ACTIVE:
            raise InvitationValidationError("邀请所属部门已归档，无法完成注册")
        user = await self.user_repo.create_user(
            {
                **user_data,
                "username": invitation_username,
                "email": email,
                "department_id": invitation.department_id,
            }
        )
        await self.session.flush()
        await self.role_assignment_service.grant_role(
            user=user,
            role_code=invitation.role.code,
            department_ids=list(invitation.department_scope_ids or []),
            expires_at=None,
            reason=invitation.reason,
            actor_id=invitation.invited_by or user.id,
        )
        invitation.used_at = datetime.now()
        invitation.used_by_user_id = user.id
        self._audit(
            actor_id=user.id,
            action="invitation.consume",
            target_id=invitation.id,
            before_data=self._snapshot(invitation, include_used=False),
            after_data=self._snapshot(invitation),
        )
        return user

    @staticmethod
    def normalize_email(email: str) -> str:
        return email.strip().lower()

    @staticmethod
    def normalize_username(username: str) -> str:
        return username.strip().lower()

    @staticmethod
    def _normalize_datetime(value: datetime | None) -> datetime | None:
        if value and value.tzinfo:
            return value.astimezone(timezone.utc).replace(tzinfo=None)
        return value

    @staticmethod
    def hash_invite_code(email: str, invite_code: str) -> str:
        payload = f"{InvitationService.normalize_email(email)}:{invite_code}".encode()
        return hmac.new(
            settings.JWT_SECRET_KEY.encode(), payload, hashlib.sha256
        ).hexdigest()

    def _audit(
        self,
        *,
        actor_id: str | None,
        action: str,
        target_id: str,
        before_data: dict[str, Any] | None = None,
        after_data: dict[str, Any] | None = None,
    ) -> None:
        self.session.add(
            AuditLogModel(
                actor_id=actor_id,
                action=action,
                target_type="invitation",
                target_id=target_id,
                before_data=before_data,
                after_data=after_data,
            )
        )

    @staticmethod
    def _snapshot(
        invitation: InvitationModel,
        *,
        include_used: bool = True,
    ) -> dict[str, Any]:
        return {
            "email": invitation.email,
            "username": invitation.username,
            "department_id": invitation.department_id,
            "role_code": invitation.role.code,
            "department_scope_ids": invitation.department_scope_ids,
            "expires_at": invitation.expires_at.isoformat(),
            "used_at": invitation.used_at.isoformat() if include_used and invitation.used_at else None,
            "reason": invitation.reason,
        }
