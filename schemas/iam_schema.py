"""IAM 管理端接口的数据契约。"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from models.user import DepartmentStatus, UserStatus


class IamDepartmentSchema(BaseModel):
    id: str
    code: str
    name: str
    description: Optional[str]
    status: DepartmentStatus
    parent_id: Optional[str]
    archived_at: Optional[datetime]

    model_config = ConfigDict(from_attributes=True)


class IamDepartmentTreeNodeSchema(IamDepartmentSchema):
    children: list["IamDepartmentTreeNodeSchema"] = Field(default_factory=list)


class DepartmentSummarySchema(BaseModel):
    direct_user_count: int
    child_department_count: int
    open_position_count: int
    active_role_scope_count: int


DEPARTMENT_CODE_PATTERN = r"^DEPT-(?:[A-Z0-9]{2,12}-)*[A-Z0-9]{2,12}$"
ROLE_CODE_PATTERN = r"^ROLE_[A-Z][A-Z0-9_]*$"
USERNAME_PATTERN = r"^[a-z][a-z0-9._-]{1,31}$"


class UsernameSchema(BaseModel):
    """用户名是可读的稳定登录标识；数据库同时以大小写不敏感唯一索引兜底。"""

    @field_validator("username", mode="before", check_fields=False)
    @classmethod
    def normalize_username(cls, value: str | None) -> str | None:
        return value.strip().lower() if isinstance(value, str) else value


class DepartmentCodeSchema(BaseModel):
    """部门码使用 DEPT-业务域-序号 格式，例如 DEPT-HR-001。"""

    @field_validator("code", mode="before", check_fields=False)
    @classmethod
    def normalize_department_code(cls, value: str | None) -> str | None:
        return value.strip().upper() if isinstance(value, str) else value


class DepartmentCreateSchema(DepartmentCodeSchema):
    code: str = Field(min_length=9, max_length=64, pattern=DEPARTMENT_CODE_PATTERN)
    name: str = Field(min_length=1, max_length=100)
    description: Optional[str] = Field(default=None, max_length=255)
    parent_id: Optional[str] = None


class DepartmentUpdateSchema(DepartmentCodeSchema):
    code: Optional[str] = Field(default=None, min_length=9, max_length=64, pattern=DEPARTMENT_CODE_PATTERN)
    name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    description: Optional[str] = Field(default=None, max_length=255)
    parent_id: Optional[str] = None


class DepartmentDependencySchema(BaseModel):
    active_users: int
    open_positions: int
    active_role_scopes: int
    active_child_departments: int
    legacy_managed_department_bindings: int
    pending_invitations: int


class IamUserSchema(BaseModel):
    id: str
    username: str
    email: str
    realname: str
    phone_number: Optional[str]
    department_id: Optional[str]
    department: Optional[IamDepartmentSchema]
    status: UserStatus
    authz_version: int
    disabled_at: Optional[datetime]
    created_at: datetime
    role_codes: list[str] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class IamUserListSchema(BaseModel):
    users: list[IamUserSchema]
    total: int


class UserProfileUpdateSchema(BaseModel):
    realname: Optional[str] = Field(default=None, min_length=1, max_length=50)
    phone_number: Optional[str] = Field(default=None, max_length=20)
    department_id: Optional[str] = None


class IamUserStatusUpdateSchema(BaseModel):
    status: UserStatus


class PrincipalRoleSchema(BaseModel):
    code: str
    name: str
    expires_at: Optional[datetime]
    department_ids: list[str] = Field(default_factory=list)


class IamPrincipalSchema(BaseModel):
    user: IamUserSchema
    roles: list[PrincipalRoleSchema]
    permissions: list[str]


class IamPermissionSchema(BaseModel):
    code: str
    name: str
    resource: str
    action: str
    description: Optional[str]

    model_config = ConfigDict(from_attributes=True)


class IamRoleSchema(BaseModel):
    id: str
    code: str
    name: str
    description: Optional[str]
    is_system: bool
    permissions: list[str]


class RolePermissionItemSchema(BaseModel):
    id: str
    name: str
    description: Optional[str]
    checked: bool


class RolePermissionModuleSchema(BaseModel):
    name: str
    permissions: list[RolePermissionItemSchema]


class RolePermissionTreeSchema(BaseModel):
    role_id: str
    role_name: str
    modules: list[RolePermissionModuleSchema]


class RolePermissionUpdateSchema(BaseModel):
    permission_ids: list[str] = Field(default_factory=list, max_length=100)
    reason: str = Field(min_length=1, max_length=255)


class UserRoleSchema(BaseModel):
    id: str
    user_id: str
    role_code: str
    assigned_by: Optional[str]
    assigned_at: datetime
    expires_at: Optional[datetime]
    revoked_at: Optional[datetime]
    revoke_reason: Optional[str]
    department_ids: list[str] = Field(default_factory=list)


class UserRoleGrantSchema(BaseModel):
    role_code: str = Field(min_length=6, max_length=64, pattern=ROLE_CODE_PATTERN)
    department_ids: list[str] = Field(default_factory=list)
    expires_at: Optional[datetime] = None
    reason: Optional[str] = Field(default=None, max_length=255)


class UserRoleRevokeSchema(BaseModel):
    reason: str = Field(min_length=1, max_length=255)


class UserRoleScopeReplaceSchema(BaseModel):
    department_ids: list[str] = Field(default_factory=list)
    reason: Optional[str] = Field(default=None, max_length=255)


class IamInvitationCreateSchema(UsernameSchema):
    email: EmailStr
    username: str = Field(min_length=2, max_length=32, pattern=USERNAME_PATTERN)
    department_id: str
    role_code: str = Field(min_length=6, max_length=64, pattern=ROLE_CODE_PATTERN)
    department_scope_ids: list[str] = Field(default_factory=list)
    expires_at: Optional[datetime] = None
    reason: Optional[str] = Field(default=None, max_length=255)


class IamInvitationSchema(BaseModel):
    id: str
    email: EmailStr
    username: str
    department_id: str
    role_code: str
    department_scope_ids: list[str]
    expires_at: datetime
    used_at: Optional[datetime]
    cancelled_at: Optional[datetime]
    created_at: datetime


class UserPasswordResetSchema(BaseModel):
    new_password: str = Field(min_length=12, max_length=128)


class AuthSessionSchema(BaseModel):
    id: str
    created_at: datetime
    last_seen_at: Optional[datetime]
    expires_at: datetime
    revoked_at: Optional[datetime]
    revoke_reason: Optional[str]
    is_current: bool


class AuditLogSchema(BaseModel):
    id: str
    actor_id: Optional[str]
    action: str
    target_type: str
    target_id: Optional[str]
    before_data: Optional[dict]
    after_data: Optional[dict]
    request_id: Optional[str]
    ip_address: Optional[str]
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AuditLogListSchema(BaseModel):
    items: list[AuditLogSchema]
    total: int
