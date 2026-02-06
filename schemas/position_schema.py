from pydantic import BaseModel, Field, ConfigDict
from datetime import datetime
from typing import Optional, List
from models.positions import EducationEnum
from schemas.user_schema import UserSchema, DepartmentSchema


class PositionBaseSchema(BaseModel):
    title: str = Field(..., description="职位标题")
    description: Optional[str] = Field(..., description="职位描述")
    requirements: str = Field(..., description="职位要求")
    min_salary: int = Field(..., description="职位最低薪资")
    max_salary: int = Field(..., description="职位最高薪资")
    deadline: Optional[datetime] = Field(None, description="职位招聘截止日期")
    recruitment_count: int = Field(1, description="职位招聘人数")
    # 最低学历要求
    education: EducationEnum = Field(..., description="最低学历要求")
    # 最低工作年限要求
    work_year: int = Field(0, description="最低工作年限要求")

class PositionCreateSchema(PositionBaseSchema):
    pass

class PositionSchema(PositionBaseSchema):
    id: str = Field(..., description="职位ID")
    creator: UserSchema = Field(..., description="职位创建者")
    department: DepartmentSchema = Field(..., description="职位所属部门")

    model_config = ConfigDict(from_attributes=True)

class PositionRespSchema(BaseModel):
    position: PositionSchema | None

class PositionListRespSchema(BaseModel):
    positions: List[PositionSchema]