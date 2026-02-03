import enum
from typing import List, Optional

from sqlalchemy import (
    String, Text, Integer,
    DateTime, Boolean, Enum as SQLAlchemyEnum, ForeignKey
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from . import BaseModel
from .user import UserModel, DepartmentModel
from datetime import datetime


class EducationEnum(str, enum.Enum):
    # 1. 大专
    COLLEGE = "大专"
    # 2. 本科
    BACHELOR = "本科"
    # 3. 硕士
    MASTER = "硕士"
    # 4. 博士
    DOCTOR = "博士"
    # 5. 未填写
    UNKNOWN = "未知"


class PositionModel(BaseModel):
    __tablename__ = "positions"

    title: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    requirements: Mapped[Optional[str]] = mapped_column(Text)
    min_salary: Mapped[Optional[int]] = mapped_column(Integer)
    max_salary: Mapped[Optional[int]] = mapped_column(Integer)
    deadline: Mapped[Optional[datetime]] = mapped_column(DateTime)
    recruitment_count: Mapped[int] = mapped_column(Integer, default=1)
    # 最低学历要求
    education: Mapped[EducationEnum] = mapped_column(SQLAlchemyEnum(EducationEnum), default=EducationEnum.UNKNOWN,nullable=False)
    # 最低工作年限要求
    work_year: Mapped[int] = mapped_column(Integer, default=0)

    is_open: Mapped[bool] = mapped_column(Boolean, default=True)

    department_id: Mapped[str] = mapped_column(ForeignKey("departments.id"))
    creator_id: Mapped[str] = mapped_column(ForeignKey("users.id"))

    department: Mapped["DepartmentModel"] = relationship(lazy="joined")
    creator: Mapped["UserModel"] = relationship(lazy="joined")
    candidates: Mapped[List["CandidateModel"]] = relationship(back_populates="position")