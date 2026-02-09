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