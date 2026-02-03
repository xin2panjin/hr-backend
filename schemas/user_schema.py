from pydantic import BaseModel, EmailStr, Field, ConfigDict
from typing import Optional
from models.user import UserStatus
from datetime import datetime


class UserLoginSchema(BaseModel):
    email: EmailStr = Field(..., description="邮箱账号")
    password: str = Field(..., description="密码", min_length=6, max_length=20)

class DepartmentSchema(BaseModel):
    id: str = Field(..., description="部门ID")
    name: str = Field(..., description="部门名称")
    description: Optional[str] = Field(..., description="部门描述")

    model_config = ConfigDict(from_attributes=True)

class UserSchema(BaseModel):
    id: str = Field(..., description="用户ID")
    username: str = Field(..., description="用户名")
    email: EmailStr = Field(..., description="邮箱")
    phone_number: Optional[str] = Field(..., description="手机号")
    realname: str = Field(..., description="真实姓名")
    avatar: Optional[str] = Field(..., description="头像")
    department: DepartmentSchema = Field(..., description="所属部门")
    status: UserStatus = Field(..., description="员工状态")
    is_superuser: bool = Field(..., description="是否超级用户")
    is_hr: bool = Field(..., description="是否HR")
    created_at: datetime = Field(..., description="创建时间")

    model_config = ConfigDict(from_attributes=True)

class UserLoginRespSchema(BaseModel):
    access_token: str = Field(..., description="access_token")
    refresh_token: str = Field(..., description="refresh_token")
    user: UserSchema = Field(..., description="用户信息")