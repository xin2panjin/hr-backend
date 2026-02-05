import enum
from typing import List, Optional
from pwdlib import PasswordHash

from sqlalchemy import String, Boolean, Enum as SEnum, ForeignKey, Table, Column, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship

from . import BaseModel, Base

password_hasher = PasswordHash.recommended()


class UserStatus(enum.Enum):
    ACTIVE = "ACTIVE"
    BLOCKED = "BLOCKED"
    RESIGNED = "RESIGNED"


# 关联表：HR管理的部门
hr_managed_departments = Table(
    "hr_managed_departments",
    Base.metadata,
    Column("user_id", ForeignKey("users.id"), primary_key=True),
    Column("department_id", ForeignKey("departments.id"), primary_key=True),
)


class UserModel(BaseModel):
    __tablename__ = "users"

    username: Mapped[str] = mapped_column(String(50), unique=True, index=True, nullable=False)
    _password: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str] = mapped_column(String(100), unique=True, index=True, nullable=False)
    phone_number: Mapped[Optional[str]] = mapped_column(String(20), unique=True, index=True)
    realname: Mapped[str] = mapped_column(String(50), nullable=False)
    avatar: Mapped[Optional[str]] = mapped_column(String(255))
    department_id: Mapped[Optional[str]] = mapped_column(ForeignKey("departments.id"))
    status: Mapped[UserStatus] = mapped_column(SEnum(UserStatus), default=UserStatus.ACTIVE)
    is_hr: Mapped[bool] = mapped_column(Boolean, default=False)
    is_superuser: Mapped[bool] = mapped_column(Boolean, default=False)

    department: Mapped[Optional["DepartmentModel"]] = relationship(back_populates="members", foreign_keys=[department_id], lazy="joined")
    managed_departments: Mapped[List["DepartmentModel"]] = relationship(
        secondary=hr_managed_departments, back_populates="managing_hrs"
    )
    dingding_user: Mapped["DingdingUserModel"] = relationship(back_populates="user", uselist=False)

    def __init__(self, **kwargs):
        if "password" in kwargs:
            raw_password = kwargs.pop("password")
            kwargs["_password"] = password_hasher.hash(raw_password)
        super().__init__(**kwargs)

    @property
    def password(self):
        return self._password

    @password.setter
    def password(self, password):
        self._password = password_hasher.hash(password)

    def check_password(self, password):
        return password_hasher.verify(password, self._password)


class DepartmentModel(BaseModel):
    __tablename__ = "departments"

    name: Mapped[str] = mapped_column(String(100), unique=True, index=True, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(String(255))
    members: Mapped[List["UserModel"]] = relationship(back_populates="department")
    managing_hrs: Mapped[List["UserModel"]] = relationship(
        secondary=hr_managed_departments, back_populates="managed_departments"
    )


class DingdingUserModel(BaseModel):
    __tablename__ = "dingding_user"
    nick: Mapped[str] = mapped_column(String(100), nullable=False)
    union_id: Mapped[str] = mapped_column(String(100), unique=True, index=True, nullable=False)
    open_id: Mapped[str] = mapped_column(String(100), unique=True, index=True, nullable=False)
    mobile: Mapped[str] = mapped_column(String(20), unique=True, index=True, nullable=False)

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    user: Mapped["UserModel"] = relationship(back_populates="dingding_user")