"""IAM 授权数据读取仓储。"""

from datetime import datetime

from sqlalchemy import func, or_, select
from sqlalchemy.orm import selectinload

from models.iam import AuditLogModel, InvitationModel, PermissionModel, RoleModel, UserRoleModel

from . import BaseRepo


class IamRepo(BaseRepo):
    async def get_audit_logs(
        self,
        *,
        page: int,
        size: int,
        actor_id: str | None = None,
        action: str | None = None,
        target_type: str | None = None,
        target_id: str | None = None,
        started_at: datetime | None = None,
        ended_at: datetime | None = None,
    ) -> tuple[list[AuditLogModel], int]:
        """按管理端筛选条件分页读取审计日志。"""

        filters = []
        if actor_id:
            filters.append(AuditLogModel.actor_id == actor_id)
        if action:
            filters.append(AuditLogModel.action == action)
        if target_type:
            filters.append(AuditLogModel.target_type == target_type)
        if target_id:
            filters.append(AuditLogModel.target_id == target_id)
        if started_at:
            filters.append(AuditLogModel.created_at >= started_at)
        if ended_at:
            filters.append(AuditLogModel.created_at <= ended_at)

        result = await self.session.scalars(
            select(AuditLogModel)
            .where(*filters)
            .order_by(AuditLogModel.created_at.desc(), AuditLogModel.id.desc())
            .limit(size)
            .offset((page - 1) * size)
        )
        total = await self.session.scalar(select(func.count(AuditLogModel.id)).where(*filters))
        return list(result), int(total or 0)
    async def list_roles(self) -> list[RoleModel]:
        result = await self.session.scalars(
            select(RoleModel)
            .options(selectinload(RoleModel.permissions))
            .order_by(RoleModel.code)
        )
        return list(result)

    async def list_permissions(self) -> list[PermissionModel]:
        result = await self.session.scalars(
            select(PermissionModel).order_by(PermissionModel.code)
        )
        return list(result)

    async def get_permissions_by_ids(self, permission_ids: list[str]) -> list[PermissionModel]:
        if not permission_ids:
            return []
        result = await self.session.scalars(
            select(PermissionModel)
            .where(PermissionModel.id.in_(permission_ids))
            .order_by(PermissionModel.resource, PermissionModel.action)
        )
        return list(result)

    async def get_role_by_id(self, role_id: str) -> RoleModel | None:
        return await self.session.scalar(
            select(RoleModel)
            .where(RoleModel.id == role_id)
            .options(selectinload(RoleModel.permissions))
        )

    async def get_role_by_code(self, role_code: str) -> RoleModel | None:
        return await self.session.scalar(
            select(RoleModel)
            .where(RoleModel.code == role_code)
            .options(selectinload(RoleModel.permissions))
        )

    async def get_pending_invitation_by_email(self, email: str) -> InvitationModel | None:
        now = datetime.now()
        return await self.session.scalar(
            select(InvitationModel)
            .where(
                InvitationModel.email == email,
                InvitationModel.used_at.is_(None),
                InvitationModel.cancelled_at.is_(None),
                InvitationModel.expires_at > now,
            )
            .with_for_update()
        )

    async def get_unresolved_invitation_by_email(self, email: str) -> InvitationModel | None:
        """读取未核销/未取消邀请；用于替换已过期邀请前的行级锁定。"""

        return await self.session.scalar(
            select(InvitationModel)
            .where(
                InvitationModel.email == email,
                InvitationModel.used_at.is_(None),
                InvitationModel.cancelled_at.is_(None),
            )
            .with_for_update()
        )

    async def get_unresolved_invitation_by_username(self, username: str) -> InvitationModel | None:
        """锁定尚未完成的同名邀请，避免两个待注册账号争用同一用户名。"""

        return await self.session.scalar(
            select(InvitationModel)
            .where(
                func.lower(InvitationModel.username) == username.strip().lower(),
                InvitationModel.used_at.is_(None),
                InvitationModel.cancelled_at.is_(None),
            )
            .with_for_update()
        )

    async def get_invitation_for_registration(
        self,
        *,
        email: str,
        invite_code_hash: str,
    ) -> InvitationModel | None:
        now = datetime.now()
        return await self.session.scalar(
            select(InvitationModel)
            .where(
                InvitationModel.email == email,
                InvitationModel.invite_code_hash == invite_code_hash,
                InvitationModel.used_at.is_(None),
                InvitationModel.cancelled_at.is_(None),
                InvitationModel.expires_at > now,
            )
            .options(selectinload(InvitationModel.role))
            .with_for_update()
        )

    async def has_invitation_for_email(self, email: str) -> bool:
        return bool(
            await self.session.scalar(
                select(InvitationModel.id).where(InvitationModel.email == email).limit(1)
            )
        )

    async def get_user_role_by_id(self, user_role_id: str) -> UserRoleModel | None:
        return await self.session.scalar(
            select(UserRoleModel)
            .where(UserRoleModel.id == user_role_id)
            .options(
                selectinload(UserRoleModel.scopes),
                selectinload(UserRoleModel.role).selectinload(RoleModel.permissions),
            )
        )

    async def get_unrevoked_user_role(
        self,
        *,
        user_id: str,
        role_id: str,
    ) -> UserRoleModel | None:
        """读取唯一约束所覆盖的用户角色，包含已过期但尚未撤销的授予。"""

        return await self.session.scalar(
            select(UserRoleModel)
            .where(
                UserRoleModel.user_id == user_id,
                UserRoleModel.role_id == role_id,
                UserRoleModel.revoked_at.is_(None),
            )
            .options(selectinload(UserRoleModel.scopes), selectinload(UserRoleModel.role))
        )

    async def get_active_user_roles(self, user_id: str) -> list[UserRoleModel]:
        """读取用户当前有效的角色、权限和部门范围。"""

        now = datetime.now()
        stmt = (
            select(UserRoleModel)
            .where(
                UserRoleModel.user_id == user_id,
                UserRoleModel.revoked_at.is_(None),
                or_(
                    UserRoleModel.expires_at.is_(None),
                    UserRoleModel.expires_at > now,
                ),
            )
            .options(
                selectinload(UserRoleModel.scopes),
                selectinload(UserRoleModel.role).selectinload(RoleModel.permissions),
            )
        )
        return list(await self.session.scalars(stmt))

    async def get_active_roles_by_user_ids(
        self,
        user_ids: list[str],
    ) -> dict[str, list[UserRoleModel]]:
        """批量加载管理端列表中的角色，避免逐用户查询。"""

        if not user_ids:
            return {}
        now = datetime.now()
        stmt = (
            select(UserRoleModel)
            .where(
                UserRoleModel.user_id.in_(user_ids),
                UserRoleModel.revoked_at.is_(None),
                or_(
                    UserRoleModel.expires_at.is_(None),
                    UserRoleModel.expires_at > now,
                ),
            )
            .options(
                selectinload(UserRoleModel.scopes),
                selectinload(UserRoleModel.role).selectinload(RoleModel.permissions),
            )
        )
        roles_by_user_id: dict[str, list[UserRoleModel]] = {}
        for user_role in await self.session.scalars(stmt):
            roles_by_user_id.setdefault(user_role.user_id, []).append(user_role)
        return roles_by_user_id
