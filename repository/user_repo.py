from . import BaseRepo
from models.user import UserModel, DingdingUserModel, DepartmentModel
from sqlalchemy import select, delete
from typing import Sequence, List
from sqlalchemy.orm import selectinload


class UserRepo(BaseRepo):
    async def create_user(self, user_data: dict) -> UserModel:
        user = UserModel(**user_data)
        self.session.add(user)
        return user

    async def get_by_id(self, user_id: str) -> UserModel | None:
        user = await self.session.scalar(
            select(UserModel).where(UserModel.id==user_id)
        )
        return user

    async def get_by_email(self, email: str) -> UserModel | None:
        user = await self.session.scalar(
            select(UserModel).where(UserModel.email == email)
        )
        return user

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

    async def assign_department(self, hr_id: str, department_ids: List[str]):
        hr_stmt = select(UserModel).where(UserModel.id==hr_id).options(selectinload(UserModel.managed_departments))
        hr: UserModel = await self.session.scalar(hr_stmt)
        if not hr:
            raise ValueError("该用户不存在！")
        department_stmt = select(DepartmentModel).where(DepartmentModel.id.in_(department_ids))
        departments = (await self.session.scalars(department_stmt)).all()
        hr.managed_departments = departments


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

    async def get_department_list(self):
        departments = await self.session.scalars(
            select(DepartmentModel)
        )
        return departments.all()

    async def delete_department(self, department_id: str) -> None:
        await self.session.execute(
            delete(DepartmentModel).where(DepartmentModel.id==department_id)
        )