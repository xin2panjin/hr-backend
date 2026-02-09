from pydantic import BaseModel, Field
from schemas.user_schema import UserSchema
from core.cache import TaskInfoSchema


class ResumeSchema(BaseModel):
    id: str = Field(..., description="简历ID")
    file_path: str = Field(..., description="简历存储路径")
    uploader: UserSchema = Field(..., description="建立上传者")

class ResumeUploadRespSchema(BaseModel):
    resume: ResumeSchema | None = Field(..., description="简历信息")

class ResumePaseSchema(BaseModel):
    resume_id: str = Field(..., description="简历ID")

class ResumeParseTaskRespSchema(BaseModel):
    task_id: str = Field(..., description="任务ID")

class ResumeParseTaskInfoRespSchema(TaskInfoSchema):
    pass
