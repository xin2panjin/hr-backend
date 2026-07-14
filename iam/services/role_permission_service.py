"""角色权限配置服务。

该服务只允许调整既有权限目录中的角色关联关系，不允许管理端创建未知权限码。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import or_, select

from iam.permissions import PermissionCode
from models.iam import AuditLogModel, RoleModel, UserRoleModel
from models.user import UserModel
from repository.iam_repo import IamRepo


class RolePermissionValidationError(ValueError):
    """角色权限配置不符合治理规则。"""


class RolePermissionService:
    """集中更新角色权限，并使所有受影响用户的旧授权版本失效。"""

    def __init__(self, session):
        self.session = session
        self.iam_repo = IamRepo(session)

    async def replace_permissions(
        self,
        *,
        role: RoleModel,
        permission_ids: list[str],
        reason: str,
        actor_id: str,
    ) -> int:
        normalized_ids = list(dict.fromkeys(permission_ids))
        if not reason.strip():
            raise RolePermissionValidationError("编辑角色权限必须填写变更原因")

        permissions = await self.iam_repo.get_permissions_by_ids(normalized_ids)
        if len(permissions) != len(normalized_ids):
            raise RolePermissionValidationError("权限配置中包含不存在的权限项")

        permission_ids_set = {permission.id for permission in permissions}
        if role.code == "ROLE_SYSTEM_ADMIN" and PermissionCode.ROLE_UPDATE_PERMISSIONS.value not in permission_ids_set:
            raise RolePermissionValidationError("系统管理员必须保留编辑角色权限能力")

        before_data = self._snapshot(role)
        role.permissions = permissions
        affected_users = await self._get_active_role_users(role.id)
        for user in affected_users:
            user.authz_version += 1

        self.session.add(
            AuditLogModel(
                actor_id=actor_id,
                action="role.permissions.replace",
                target_type="role",
                target_id=role.id,
                before_data=before_data,
                after_data={
                    "role_code": role.code,
                    "permission_ids": sorted(permission_ids_set),
                    "affected_user_count": len(affected_users),
                    "reason": reason.strip(),
                },
            )
        )
        return len(affected_users)

    async def _get_active_role_users(self, role_id: str) -> list[UserModel]:
        now = datetime.now()
        result = await self.session.scalars(
            select(UserModel)
            .join(UserRoleModel, UserRoleModel.user_id == UserModel.id)
            .where(
                UserRoleModel.role_id == role_id,
                UserRoleModel.revoked_at.is_(None),
                or_(UserRoleModel.expires_at.is_(None), UserRoleModel.expires_at > now),
            )
        )
        return list(result.unique())

    @staticmethod
    def _snapshot(role: RoleModel) -> dict:
        return {
            "role_code": role.code,
            "permission_ids": sorted(permission.id for permission in role.permissions),
        }
