from pydantic import BaseModel, EmailStr
from typing import Literal
from schemas.agent_schema import AgentCandidateSchema

class InviteInfoSchema(BaseModel):
    email: EmailStr
    department_id: str
    invite_code: str

class DingTalkTokenInfoSchema(BaseModel):
    access_token: str
    refresh_token: str
    user_id: str

class TaskInfoSchema(BaseModel):
    task_id: str
    status: Literal['pending', 'done', 'failed']
    result: AgentCandidateSchema | None = None
    error: str | None = None


class ResumeParseTaskOwnerSchema(BaseModel):
    """简历解析任务的内部归属记录，不直接对 API 调用方返回。"""

    task_id: str
    owner_id: str
    resume_id: str
