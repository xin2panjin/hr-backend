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