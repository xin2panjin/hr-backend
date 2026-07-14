from . import BaseRepo
from models.user import (
    DepartmentModel,
    DepartmentStatus,
    DingdingUserModel,
    UserModel,
    UserStatus,
)
from models.positions import PositionModel
from models.iam import RoleModel, UserRoleModel, UserRoleScopeModel
from datetime import datetime

from sqlalchemy import func, or_, select
from typing import Sequence


class UserRepo(BaseRepo):
    async def create_user(self, user_data: dict) -> UserModel:
        user = UserModel(**user_data)
        self.session.add(user)
        return user

    async def get_by_id(self, user_id: str) -> UserModel | None:
        user = await self.session.scalar(select(UserModel).where(UserModel.id==user_id))
        return user

    async def get_by_email(self, email: str) -> UserModel | None:
        user = await self.session.scalar(
            select(UserModel).where(func.lower(UserModel.email) == email.strip().lower())
        )
        return user

    async def get_by_username(self, username: str) -> UserModel | None:
        return await self.session.scalar(
            select(UserModel).where(func.lower(UserModel.username) == username.strip().lower())
        )

    async def get_by_login_account(self, account: str) -> UserModel | None:
        """用户名与邮箱共用登录入口，统一按大小写不敏感方式匹配。"""

        normalized = account.strip().lower()
        return await self.session.scalar(
            select(UserModel).where(
                or_(
                    func.lower(UserModel.username) == normalized,
                    func.lower(UserModel.email) == normalized,
                )
            )
        )

    async def get_user_list(
        self,
        page: int = 1,
        size: int = 10,
        department_id: str|None = None
    ) -> Sequence[UserModel] | None:
        stmt = select(UserModel)
        if department_id:
            stmt = stmt.where(UserModel.department_id==department_id)
        limit = size
        offset = (page-1)*size
        stmt = stmt.limit(limit).offset(offset).order_by(UserModel.created_at.desc())
        users = await self.session.scalars(stmt)
        return users.all()

    async def get_user_count(self, department_id: str|None = None):
        stmt = select(func.count(UserModel.id))
        if department_id:
            stmt = stmt.where(UserModel.department_id == department_id)
        total = await self.session.scalar(stmt)
        return total

    async def get_iam_user_list(
        self,
        *,
        page: int,
        size: int,
        department_id: str | None = None,
        include_descendants: bool = False,
        role_code: str | None = None,
        keyword: str | None = None,
        user_status: UserStatus | None = None,
    ) -> tuple[Sequence[UserModel], int]:
        """供 IAM 管理页使用的分页用户查询。"""

        filters = []
        if department_id:
            department_ids = [department_id]
            if include_descendants:
                department_ids.extend(
                    await DepartmentRepo(self.session).get_descendant_ids(department_id)
                )
            filters.append(UserModel.department_id.in_(department_ids))
        if user_status:
            filters.append(UserModel.status == user_status)
        if keyword and keyword.strip():
            pattern = f"%{keyword.strip()}%"
            filters.append(
                or_(
                    UserModel.realname.ilike(pattern),
                    UserModel.email.ilike(pattern),
                    UserModel.username.ilike(pattern),
                )
            )

        stmt = select(UserModel)
        count_stmt = select(func.count(func.distinct(UserModel.id)))
        if role_code:
            now = datetime.now()
            role_filters = (
                UserRoleModel.revoked_at.is_(None),
                or_(UserRoleModel.expires_at.is_(None), UserRoleModel.expires_at > now),
                RoleModel.code == role_code,
            )
            stmt = stmt.join(UserRoleModel, UserRoleModel.user_id == UserModel.id).join(
                RoleModel, RoleModel.id == UserRoleModel.role_id
            ).where(*role_filters)
            count_stmt = count_stmt.select_from(UserModel).join(
                UserRoleModel, UserRoleModel.user_id == UserModel.id
            ).join(RoleModel, RoleModel.id == UserRoleModel.role_id).where(*role_filters)
        else:
            count_stmt = count_stmt.select_from(UserModel)
        stmt = stmt.where(*filters)
        count_stmt = count_stmt.where(*filters)
        users = await self.session.scalars(
            stmt.order_by(UserModel.created_at.desc()).limit(size).offset((page - 1) * size)
        )
        return users.unique().all(), int(await self.session.scalar(count_stmt) or 0)

    async def set_dingding_user(self, user_id: str, dingding_user_data: dict) -> DingdingUserModel:
        user = await self.get_by_id(user_id)
        if not user:
            raise ValueError("设置钉钉的用户不存在！")

        dingding_user = await self.session.scalar(
            select(DingdingUserModel).where(DingdingUserModel.user_id==user_id)
        )
        if dingding_user:
            for key, value in dingding_user_data.items():
                setattr(dingding_user, key, value)
        else:
            dingding_user = DingdingUserModel(**dingding_user_data, user_id=user_id)
            self.session.add(dingding_user)
        return dingding_user

    async def get_dingding_user(self, user_id: str) -> DingdingUserModel | None:
        stmt = select(DingdingUserModel).where(DingdingUserModel.user_id==user_id)
        dingding_user = await self.session.scalar(stmt)
        return dingding_user

class DepartmentRepo(BaseRepo):
    async def create_department(self, department_data: dict) -> DepartmentModel:
        department = DepartmentModel(**department_data)
        self.session.add(department)
        return department

    async def get_by_id(self, department_id: str) -> DepartmentModel | None:
        department = await self.session.scalar(
            select(DepartmentModel).where(DepartmentModel.id==department_id)
        )
        return department

    async def get_by_name(self, department_name: str) -> DepartmentModel | None:
        department = await self.session.scalar(
            select(DepartmentModel).where(DepartmentModel.name == department_name)
        )
        return department

    async def get_by_code(self, department_code: str) -> DepartmentModel | None:
        return await self.session.scalar(
            select(DepartmentModel).where(DepartmentModel.code == department_code)
        )

    async def get_department_list(
        self,
        *,
        include_archived: bool = False,
    ) -> Sequence[DepartmentModel]:
        stmt = select(DepartmentModel).order_by(DepartmentModel.name)
        if not include_archived:
            stmt = stmt.where(DepartmentModel.status == DepartmentStatus.ACTIVE)
        departments = await self.session.scalars(stmt)
        return departments.all()

    async def get_descendant_ids(self, department_id: str) -> list[str]:
        """使用已加载的部门主数据计算下级节点，避免数据库方言相关递归 SQL。"""

        departments = await self.get_department_list(include_archived=False)
        children_by_parent: dict[str | None, list[str]] = {}
        for department in departments:
            children_by_parent.setdefault(department.parent_id, []).append(department.id)

        descendants: list[str] = []
        pending = list(children_by_parent.get(department_id, []))
        visited = {department_id}
        while pending:
            current_id = pending.pop()
            if current_id in visited:
                continue
            visited.add(current_id)
            descendants.append(current_id)
            pending.extend(children_by_parent.get(current_id, []))
        return descendants

    async def get_department_summary(self, department_id: str) -> dict[str, int]:
        """返回部门工作台摘要，不包含归档依赖以外的业务明细。"""

        now = datetime.now()
        direct_user_count = await self.session.scalar(
            select(func.count(UserModel.id)).where(UserModel.department_id == department_id)
        )
        child_department_count = await self.session.scalar(
            select(func.count(DepartmentModel.id)).where(
                DepartmentModel.parent_id == department_id,
                DepartmentModel.status == DepartmentStatus.ACTIVE,
            )
        )
        open_position_count = await self.session.scalar(
            select(func.count(PositionModel.id)).where(
                PositionModel.department_id == department_id,
                PositionModel.is_open.is_(True),
            )
        )
        active_role_scope_count = await self.session.scalar(
            select(func.count(UserRoleScopeModel.id))
            .join(UserRoleModel, UserRoleScopeModel.user_role_id == UserRoleModel.id)
            .where(
                UserRoleScopeModel.department_id == department_id,
                UserRoleModel.revoked_at.is_(None),
                or_(UserRoleModel.expires_at.is_(None), UserRoleModel.expires_at > now),
            )
        )
        return {
            "direct_user_count": int(direct_user_count or 0),
            "child_department_count": int(child_department_count or 0),
            "open_position_count": int(open_position_count or 0),
            "active_role_scope_count": int(active_role_scope_count or 0),
        }

    async def get_archive_dependencies(self, department_id: str) -> dict[str, int]:
        """统计归档会破坏的现有有效关联，不执行任何写操作。"""

        now = datetime.now()
        active_users = await self.session.scalar(
            select(func.count(UserModel.id)).where(
                UserModel.department_id == department_id,
                UserModel.status.in_((UserStatus.ACTIVE, UserStatus.BLOCKED)),
            )
        )
        open_positions = await self.session.scalar(
            select(func.count(PositionModel.id)).where(
                PositionModel.department_id == department_id,
                PositionModel.is_open.is_(True),
            )
        )
        active_role_scopes = await self.session.scalar(
            select(func.count(UserRoleScopeModel.id))
            .join(UserRoleModel, UserRoleScopeModel.user_role_id == UserRoleModel.id)
            .where(
                UserRoleScopeModel.department_id == department_id,
                UserRoleModel.revoked_at.is_(None),
                or_(
                    UserRoleModel.expires_at.is_(None),
                    UserRoleModel.expires_at > now,
                ),
            )
        )
        active_child_departments = await self.session.scalar(
            select(func.count(DepartmentModel.id)).where(
                DepartmentModel.parent_id == department_id,
                DepartmentModel.status == DepartmentStatus.ACTIVE,
            )
        )
        return {
            "active_users": int(active_users or 0),
            "open_positions": int(open_positions or 0),
            "active_role_scopes": int(active_role_scopes or 0),
            "active_child_departments": int(active_child_departments or 0),
            "legacy_managed_department_bindings": 0,
            "pending_invitations": 0,
        }
