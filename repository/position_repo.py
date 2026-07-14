from . import BaseRepo
from models.user import UserModel
from datetime import datetime
from sqlalchemy import select, delete, func, or_
from typing import Sequence
from models.positions import EducationEnum, PositionModel
from iam.policies.position_policy import PositionPolicy


class PositionRepo(BaseRepo):
    async def create_position(self, position_data: dict) -> PositionModel:
        position = PositionModel(**position_data)
        self.session.add(position)
        return position

    async def get_possition_list(self,
        user: UserModel,
        page: int = 1,
        size: int = 10,
        keyword: str | None = None,
        department_id: str | None = None,
        is_open: bool | None = None,
        education: EducationEnum | None = None,
        work_year_min: int | None = None,
        work_year_max: int | None = None,
        created_at_start: datetime | None = None,
        created_at_end: datetime | None = None,
    ) -> tuple[Sequence[PositionModel], int]:
        filters = []
        if department_id:
            filters.append(PositionModel.department_id == department_id)
        if is_open is not None:
            filters.append(PositionModel.is_open.is_(is_open))
        if education is not None:
            filters.append(PositionModel.education == education)
        if work_year_min is not None:
            filters.append(PositionModel.work_year >= work_year_min)
        if work_year_max is not None:
            filters.append(PositionModel.work_year <= work_year_max)
        if created_at_start is not None:
            filters.append(PositionModel.created_at >= created_at_start)
        if created_at_end is not None:
            filters.append(PositionModel.created_at <= created_at_end)
        if keyword and keyword.strip():
            pattern = f"%{keyword.strip()}%"
            filters.append(
                or_(
                    PositionModel.title.ilike(pattern),
                    PositionModel.description.ilike(pattern),
                    PositionModel.requirements.ilike(pattern),
                )
            )

        scope = PositionPolicy.resolve_scope(user)
        stmt = PositionPolicy.apply_sql_scope(select(PositionModel), scope, PositionModel).where(*filters)
        count_stmt = PositionPolicy.apply_sql_scope(
            select(func.count(PositionModel.id)),
            scope,
            PositionModel,
        ).where(*filters)
        total = int(await self.session.scalar(count_stmt) or 0)
        # 分页
        limit = size
        offset = (page - 1) * size
        stmt = stmt.limit(limit).offset(offset).order_by(PositionModel.created_at.desc())
        positions = (await self.session.scalars(stmt)).all()
        return positions, total

    async def get_by_id(self, position_id: str) -> PositionModel | None:
        stmt = select(PositionModel).where(PositionModel.id == position_id)
        position = await self.session.scalar(stmt)
        return position

    async def delete_position(self, position_id: str):
        stmt = delete(PositionModel).where(PositionModel.id == position_id)
        await self.session.execute(stmt)
