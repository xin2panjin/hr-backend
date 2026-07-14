from pydantic import BaseModel, Field, ConfigDict
from schemas.user_schema import UserSchema
from core.cache import TaskInfoSchema
from models.candidate import GenderEnum, CandidateStatusEnum
from schemas.position_schema import PositionSchema
from typing import Optional
from datetime import datetime


class ResumeSchema(BaseModel):
    id: str = Field(..., description="简历ID")
    file_path: str = Field(..., description="简历存储路径")
    uploader: UserSchema = Field(..., description="建立上传者")

    model_config = ConfigDict(from_attributes=True)

class ResumeUploadRespSchema(BaseModel):
    resume: ResumeSchema | None = Field(..., description="简历信息")

class ResumePaseSchema(BaseModel):
    resume_id: str = Field(..., description="简历ID")

class ResumeParseTaskRespSchema(BaseModel):
    task_id: str = Field(..., description="任务ID")

class ResumeParseTaskInfoRespSchema(TaskInfoSchema):
    pass

class CandidateCreateSchema(BaseModel):
    name: str = Field(..., description="候选人姓名")
    email: str = Field(..., description="候选人邮箱")
    gender: GenderEnum = Field(GenderEnum.UNKNOWN, description="候选人性别")
    birthday: str | None = Field(None, description="候选人出生日期，如果只有年份，那么就把日期设置为1月1日")
    phone_number: str | None = Field(None, description="候选人电话")
    work_experience: str | None = Field(None, description="候选人工作经历")
    project_experience: str | None = Field(None, description="候选人项目经历")
    education_experience: str | None = Field(None, description="候选人教育经历")
    self_evaluation: str | None = Field(None, description="候选人自我评价")
    other_information: str | None = Field(None, description="候选人其他信息")
    skills: str | None = Field(None, description="候选人技能")

    position_id: str = Field(..., description="候选人申请职位ID")
    resume_id: str = Field(..., description="候选人的简历ID")


class CandidateSchema(BaseModel):
    id: str = Field(..., description="候选人ID")
    name: str = Field(..., description="候选人姓名")
    email: str = Field(..., description="候选人邮箱")
    gender: GenderEnum = Field(GenderEnum.UNKNOWN, description="候选人性别")
    birthday: str | None = Field(None, description="候选人出生日期，如果只有年份，那么就把日期设置为1月1日")
    phone_number: str | None = Field(None, description="候选人电话")
    work_experience: str | None = Field(None, description="候选人工作经历")
    project_experience: str | None = Field(None, description="候选人项目经历")
    education_experience: str | None = Field(None, description="候选人教育经历")
    self_evaluation: str | None = Field(None, description="候选人自我评价")
    other_information: str | None = Field(None, description="候选人其他信息")
    skills: str | None = Field(None, description="候选人技能")
    status: CandidateStatusEnum | str | None = Field(None, description="候选人状态")

    position: PositionSchema = Field(..., description="候选人申请的职位信息")
    resume: ResumeSchema = Field(..., description="候选人的简历信息")
    creator: UserSchema = Field(..., description="创建该候选人的信息")

    model_config = ConfigDict(from_attributes=True)

class CandidateStatusUpdateSchema(BaseModel):
    status: CandidateStatusEnum = Field(..., description="候选人状态")
    interview_time: Optional[datetime] = Field(None, description="面试时间，当状态变更为待面试时必填")
    rejection_reason: Optional[str] = Field(None, description="未通过原因，当状态变更为面试未通过时必填")

class CandidateListSchema(BaseModel):
    candidates: list[CandidateSchema]
    total: int = Field(..., description="符合条件的候选人总数")
    page: int = Field(..., description="当前页码")
    size: int = Field(..., description="每页数量")

class CandidateAIScoreSchema(BaseModel):
    id: str
    work_experience_score: int
    technical_skills_score: int
    soft_skills_score: int
    educational_background_score: int
    project_experience_score: int
    overall_score: int
    summary: str
    strengths: list[str]
    weaknesses: list[str]
    candidate_id: str

    model_config = ConfigDict(from_attributes=True)

class CandidateAIScoreRespSchema(BaseModel):
    ai_score: CandidateAIScoreSchema
