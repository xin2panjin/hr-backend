"""组织主数据（用户、部门）生命周期服务。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from models.iam import AuditLogModel, UserRoleModel
from models.user import DepartmentModel, DepartmentStatus, UserModel, UserStatus
from repository.user_repo import DepartmentRepo, UserRepo


class OrganizationValidationError(ValueError):
    """请求字段或组织关系不符合规则。"""


class DepartmentArchiveConflict(Exception):
    """归档会破坏有效依赖时抛出，并携带前端可展示的统计。"""

    def __init__(self, dependencies: dict[str, int]):
        self.dependencies = dependencies
        super().__init__("部门仍存在有效依赖，不能归档")


class OrganizationService:
    """将组织规则从 Router 中收敛，方便后续切换到 RBAC permission guard。"""

    def __init__(self, session):
        self.session = session
        self.user_repo = UserRepo(session)
        self.department_repo = DepartmentRepo(session)

    async def create_department(
        self,
        *,
        data: dict[str, Any],
        actor_id: str,
    ) -> DepartmentModel:
        await self._ensure_department_unique(code=data["code"], name=data["name"])
        await self._validate_parent(parent_id=data.get("parent_id"))
        department = await self.department_repo.create_department(data)
        self._audit(
            actor_id=actor_id,
            action="department.create",
            target_type="department",
            target_id=department.id,
            after_data=self._department_snapshot(department),
        )
        return department

    async def update_department(
        self,
        *,
        department: DepartmentModel,
        data: dict[str, Any],
        actor_id: str,
    ) -> DepartmentModel:
        if department.status != DepartmentStatus.ACTIVE:
            raise OrganizationValidationError("归档部门不可修改")

        code = data.get("code")
        name = data.get("name")
        if code and code != department.code:
            await self._ensure_department_unique(code=code, name=None)
        if name and name != department.name:
            await self._ensure_department_unique(code=None, name=name)
        if "parent_id" in data:
            await self._validate_parent(
                parent_id=data["parent_id"],
                current_department_id=department.id,
            )

        before_data = self._department_snapshot(department)
        for field in ("code", "name", "description", "parent_id"):
            if field in data:
                setattr(department, field, data[field])
        self._audit(
            actor_id=actor_id,
            action="department.update",
            target_type="department",
            target_id=department.id,
            before_data=before_data,
            after_data=self._department_snapshot(department),
        )
        return department

    async def archive_department(
        self,
        *,
        department: DepartmentModel,
        actor_id: str,
    ) -> DepartmentModel:
        if department.status == DepartmentStatus.ARCHIVED:
            return department
        dependencies = await self.department_repo.get_archive_dependencies(department.id)
        if any(dependencies.values()):
            raise DepartmentArchiveConflict(dependencies)

        before_data = self._department_snapshot(department)
        department.status = DepartmentStatus.ARCHIVED
        department.archived_at = datetime.now()
        department.archived_by = actor_id
        self._audit(
            actor_id=actor_id,
            action="department.archive",
            target_type="department",
            target_id=department.id,
            before_data=before_data,
            after_data=self._department_snapshot(department),
        )
        return department

    async def update_user_profile(
        self,
        *,
        user: UserModel,
        data: dict[str, Any],
        actor_id: str,
    ) -> UserModel:
        if "department_id" in data:
            department = await self.department_repo.get_by_id(data["department_id"])
            if not department or department.status != DepartmentStatus.ACTIVE:
                raise OrganizationValidationError("目标部门不存在或已归档")

        before_data = self._user_snapshot(user)
        for field in ("realname", "phone_number", "department_id"):
            if field in data:
                setattr(user, field, data[field])
        if data:
            user.authz_version += 1
        self._audit(
            actor_id=actor_id,
            action="user.update",
            target_type="user",
            target_id=user.id,
            before_data=before_data,
            after_data=self._user_snapshot(user),
        )
        return user

    async def update_user_status(
        self,
        *,
        user: UserModel,
        user_status: UserStatus,
        actor_id: str,
    ) -> UserModel:
        before_data = self._user_snapshot(user)
        user.status = user_status
        user.authz_version += 1
        if user_status == UserStatus.ACTIVE:
            user.disabled_at = None
            user.disabled_by = None
        else:
            user.disabled_at = datetime.now()
            user.disabled_by = actor_id

        # 离职即撤销全部角色；禁用通过 authz_version 为将来的会话层提供失效信号。
        if user_status == UserStatus.RESIGNED:
            for user_role in await self._get_active_user_roles(user.id):
                user_role.revoked_at = datetime.now()
                user_role.revoke_reason = "用户离职"

        if user_status != UserStatus.ACTIVE:
            from iam.services.auth_session_service import AuthSessionService

            await AuthSessionService(self.session).revoke_user_sessions(
                user_id=user.id,
                reason=f"user_status_{user_status.value.lower()}",
                actor_id=actor_id,
            )

        self._audit(
            actor_id=actor_id,
            action="user.status.update",
            target_type="user",
            target_id=user.id,
            before_data=before_data,
            after_data=self._user_snapshot(user),
        )
        return user

    async def _ensure_department_unique(
        self,
        *,
        code: str | None,
        name: str | None,
    ) -> None:
        if code and await self.department_repo.get_by_code(code):
            raise OrganizationValidationError("部门编码已存在")
        if name and await self.department_repo.get_by_name(name):
            raise OrganizationValidationError("部门名称已存在")

    async def _validate_parent(
        self,
        *,
        parent_id: str | None,
        current_department_id: str | None = None,
    ) -> None:
        if not parent_id:
            return
        if parent_id == current_department_id:
            raise OrganizationValidationError("部门不能设置自身为父部门")

        visited: set[str] = set()
        parent = await self.department_repo.get_by_id(parent_id)
        while parent:
            if parent.status != DepartmentStatus.ACTIVE:
                raise OrganizationValidationError("父部门不存在或已归档")
            if parent.id == current_department_id:
                raise OrganizationValidationError("不能将部门移动到自身的子孙节点")
            if parent.id in visited:
                raise OrganizationValidationError("部门层级存在循环")
            visited.add(parent.id)
            parent = (
                await self.department_repo.get_by_id(parent.parent_id)
                if parent.parent_id
                else None
            )

    async def _get_active_user_roles(self, user_id: str) -> list[UserRoleModel]:
        from sqlalchemy import select

        result = await self.session.scalars(
            select(UserRoleModel).where(
                UserRoleModel.user_id == user_id,
                UserRoleModel.revoked_at.is_(None),
            )
        )
        return list(result)

    def _audit(
        self,
        *,
        actor_id: str,
        action: str,
        target_type: str,
        target_id: str,
        before_data: dict[str, Any] | None = None,
        after_data: dict[str, Any] | None = None,
    ) -> None:
        self.session.add(
            AuditLogModel(
                actor_id=actor_id,
                action=action,
                target_type=target_type,
                target_id=target_id,
                before_data=before_data,
                after_data=after_data,
            )
        )

    @staticmethod
    def _department_snapshot(department: DepartmentModel) -> dict[str, Any]:
        return {
            "code": department.code,
            "name": department.name,
            "description": department.description,
            "status": department.status.value,
            "parent_id": department.parent_id,
        }

    @staticmethod
    def _user_snapshot(user: UserModel) -> dict[str, Any]:
        return {
            "realname": user.realname,
            "phone_number": user.phone_number,
            "department_id": user.department_id,
            "status": user.status.value,
            "authz_version": user.authz_version,
        }
