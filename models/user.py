import enum
from datetime import datetime
from typing import List, Optional
from pwdlib import PasswordHash

from sqlalchemy import String, Enum as SEnum, ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship

from . import BaseModel, Base

password_hasher = PasswordHash.recommended()


class UserStatus(enum.Enum):
    ACTIVE = "ACTIVE"
    BLOCKED = "BLOCKED"
    RESIGNED = "RESIGNED"


class DepartmentStatus(str, enum.Enum):
    """组织部门的生命周期状态。"""

    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"


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
    # 角色、范围或账号状态变更时递增，后续会话校验以此实现即时失效。
    authz_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    last_login_at: Mapped[Optional[datetime]] = mapped_column()
    disabled_at: Mapped[Optional[datetime]] = mapped_column()
    disabled_by: Mapped[Optional[str]] = mapped_column(ForeignKey("users.id"))

    department: Mapped[Optional["DepartmentModel"]] = relationship(back_populates="members", foreign_keys=[department_id], lazy="joined")
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

    # code 是稳定机器标识；名称可修改，仍保持全局唯一以兼容当前组织模型。
    code: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(100), unique=True, index=True, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(String(255))
    status: Mapped[DepartmentStatus] = mapped_column(
        SEnum(DepartmentStatus, values_callable=lambda obj: [item.value for item in obj]),
        default=DepartmentStatus.ACTIVE,
        nullable=False,
    )
    parent_id: Mapped[Optional[str]] = mapped_column(ForeignKey("departments.id"))
    archived_at: Mapped[Optional[datetime]] = mapped_column()
    archived_by: Mapped[Optional[str]] = mapped_column(ForeignKey("users.id"))
    members: Mapped[List["UserModel"]] = relationship(
        back_populates="department",
        foreign_keys="UserModel.department_id",
    )


class DingdingUserModel(BaseModel):
    __tablename__ = "dingding_user"
    nick: Mapped[str] = mapped_column(String(100), nullable=False)
    union_id: Mapped[str] = mapped_column(String(100), unique=True, index=True, nullable=False)
    open_id: Mapped[str] = mapped_column(String(100), unique=True, index=True, nullable=False)
    mobile: Mapped[str] = mapped_column(String(20), unique=True, index=True, nullable=False)

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    user: Mapped["UserModel"] = relationship(back_populates="dingding_user")
