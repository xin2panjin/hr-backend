from . import BaseRepo
from models.user import UserModel
from sqlalchemy import select, delete
from typing import Sequence, List
from sqlalchemy.orm import selectinload
from models.positions import PositionModel


class PositionRepo(BaseRepo):
    async def create_position(self, position_data: dict) -> PositionModel:
        position = PositionModel(**position_data)
        self.session.add(position)
        return position

    async def get_possition_list(self,
        user: UserModel,
        page: int = 1,
        size: int = 10
    ) -> Sequence[PositionModel]:
        stmt = select(PositionModel)
        # 1. 如果是hr，那么只返回该hr负责的部门的职位
        # 2. 如果是其他部门的员工，那么只要返回该员工所在部门的职位就可以了
        # 3. 如果是superuser，那么就没有条件
        if user.is_hr and (not user.is_superuser):
            department_ids = [d.id for d in user.managed_departments]
            stmt = stmt.where(PositionModel.department_id.in_(department_ids))
        elif (not user.is_hr) and (not user.is_superuser):
            stmt = stmt.where(PositionModel.department_id == user.department_id)
        # 分页
        limit = size
        offset = (page - 1) * size
        stmt = stmt.limit(limit).offset(offset).order_by(PositionModel.created_at.desc())
        positions = (await self.session.scalars(stmt)).all()
        return positions

    async def get_by_id(self, position_id: str) -> PositionModel | None:
        stmt = select(PositionModel).where(PositionModel.id == position_id)
        position = await self.session.scalar(stmt)
        return position

    async def delete_position(self, position_id: str):
        stmt = delete(PositionModel).where(PositionModel.id == position_id)
        await self.session.execute(stmt)