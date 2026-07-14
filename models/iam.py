"""IAM（身份认证与授权）领域的数据模型。"""

import enum
from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, JSON, String, Table, Text
from sqlalchemy import Enum as SQLAlchemyEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from . import Base, BaseModel


class ScopeTypeEnum(str, enum.Enum):
    """用户角色的可配置范围类型。"""

    DEPARTMENT = "DEPARTMENT"


role_permissions = Table(
    "role_permissions",
    Base.metadata,
    Column("role_id", ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True),
    Column(
        "permission_id",
        ForeignKey("permissions.id", ondelete="CASCADE"),
        primary_key=True,
    ),
)


class RoleModel(BaseModel):
    __tablename__ = "roles"

    code: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    is_system: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    permissions: Mapped[list["PermissionModel"]] = relationship(
        secondary=role_permissions,
        back_populates="roles",
        lazy="selectin",
    )


class PermissionModel(BaseModel):
    __tablename__ = "permissions"

    code: Mapped[str] = mapped_column(String(100), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    resource: Mapped[str] = mapped_column(String(64), nullable=False)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)

    roles: Mapped[list[RoleModel]] = relationship(
        secondary=role_permissions,
        back_populates="permissions",
        lazy="selectin",
    )


class UserRoleModel(BaseModel):
    __tablename__ = "user_roles"

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    role_id: Mapped[str] = mapped_column(ForeignKey("roles.id"), nullable=False, index=True)
    assigned_by: Mapped[Optional[str]] = mapped_column(ForeignKey("users.id"))
    assigned_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, nullable=False)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    revoke_reason: Mapped[Optional[str]] = mapped_column(String(255))

    role: Mapped[RoleModel] = relationship(lazy="joined")
    scopes: Mapped[list["UserRoleScopeModel"]] = relationship(
        back_populates="user_role",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class UserRoleScopeModel(BaseModel):
    __tablename__ = "user_role_scopes"

    user_role_id: Mapped[str] = mapped_column(
        ForeignKey("user_roles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    scope_type: Mapped[ScopeTypeEnum] = mapped_column(
        SQLAlchemyEnum(ScopeTypeEnum, values_callable=lambda obj: [item.value for item in obj]),
        nullable=False,
    )
    department_id: Mapped[Optional[str]] = mapped_column(ForeignKey("departments.id"))

    user_role: Mapped[UserRoleModel] = relationship(back_populates="scopes")


class InvitationModel(BaseModel):
    """持久化邀请：只存验证码摘要，不存可直接使用的明文验证码。"""

    __tablename__ = "invitations"

    email: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    # 用户名由管理员创建邀请时确定，注册时仅核验，不允许自行替换。
    username: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    department_id: Mapped[str] = mapped_column(ForeignKey("departments.id"), nullable=False)
    role_id: Mapped[str] = mapped_column(ForeignKey("roles.id"), nullable=False)
    department_scope_ids: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    invite_code_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    invited_by: Mapped[Optional[str]] = mapped_column(ForeignKey("users.id"))
    reason: Mapped[Optional[str]] = mapped_column(String(255))
    used_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    used_by_user_id: Mapped[Optional[str]] = mapped_column(ForeignKey("users.id"))
    cancelled_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    cancelled_by: Mapped[Optional[str]] = mapped_column(ForeignKey("users.id"))

    role: Mapped[RoleModel] = relationship(lazy="joined", foreign_keys=[role_id])


class AuthSessionModel(BaseModel):
    """服务端认证会话；refresh token 仅保存 jti 摘要。"""

    __tablename__ = "auth_sessions"

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    authz_version: Mapped[int] = mapped_column(nullable=False)
    refresh_jti_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    last_seen_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    revoke_reason: Mapped[Optional[str]] = mapped_column(String(255))
    replaced_by_id: Mapped[Optional[str]] = mapped_column(ForeignKey("auth_sessions.id"))


class OAuthStateModel(BaseModel):
    """第三方 OAuth 的一次性 state 摘要记录。"""

    __tablename__ = "oauth_states"

    provider: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    state_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    redirect_uri: Mapped[str] = mapped_column(String(500), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    consumed_at: Mapped[Optional[datetime]] = mapped_column(DateTime)


class AuditLogModel(BaseModel):
    __tablename__ = "audit_logs"

    actor_id: Mapped[Optional[str]] = mapped_column(ForeignKey("users.id"), index=True)
    action: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    target_type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    target_id: Mapped[Optional[str]] = mapped_column(String(100), index=True)
    before_data: Mapped[Optional[dict]] = mapped_column(JSON)
    after_data: Mapped[Optional[dict]] = mapped_column(JSON)
    request_id: Mapped[Optional[str]] = mapped_column(String(100), index=True)
    ip_address: Mapped[Optional[str]] = mapped_column(String(64))
