from datetime import datetime
from pydantic import BaseModel, EmailStr, Field

from models.candidate_communication import CandidateFollowupTaskStatusEnum, CandidateTaskPriorityEnum


class CandidatePortalSendCodeSchema(BaseModel):
    email: EmailStr


class CandidatePortalVerifyCodeSchema(CandidatePortalSendCodeSchema):
    code: str = Field(min_length=6, max_length=6, pattern=r"^\d{6}$")


class CandidatePortalSendMessageSchema(BaseModel):
    content: str = Field(min_length=1, max_length=5000)


class HRSendMessageSchema(CandidatePortalSendMessageSchema):
    pass


class UpdateFollowupTaskSchema(BaseModel):
    status: CandidateFollowupTaskStatusEnum


class CreateFollowupTaskNoteSchema(BaseModel):
    content: str = Field(min_length=1, max_length=2000)


class CandidateMessageSchema(BaseModel):
    id: str
    sender_type: str
    content: str
    sender_name: str | None = None
    created_at: datetime


class CandidatePortalApplicationSchema(BaseModel):
    candidate_id: str
    candidate_name: str
    position_title: str
    status: str
    applied_at: datetime
    conversation_id: str | None = None
    last_message_at: datetime | None = None


class CandidateInsightSchema(BaseModel):
    id: str
    summary: str
    stage: str | None = None
    intent: str | None = None
    confirmed_facts: list = Field(default_factory=list)
    candidate_requests: list = Field(default_factory=list)
    hr_commitments: list = Field(default_factory=list)
    risks: list = Field(default_factory=list)
    next_step: str | None = None
    evidence: list = Field(default_factory=list)
    created_at: datetime


class CandidateFollowupTaskSchema(BaseModel):
    id: str
    candidate_id: str
    conversation_id: str
    candidate_name: str | None = None
    position_title: str | None = None
    assignee_name: str | None = None
    title: str
    task_type: str
    priority: str
    status: str
    due_at: datetime | None = None
    evidence: list = Field(default_factory=list)
    created_at: datetime


class CandidateFollowupTaskNoteSchema(BaseModel):
    id: str
    content: str
    author_name: str | None = None
    created_at: datetime


class CandidateInsightExtractionSchema(BaseModel):
    summary: str = ""
    stage: str | None = None
    intent: str | None = None
    confirmed_facts: list[str] = Field(default_factory=list)
    candidate_requests: list[str] = Field(default_factory=list)
    hr_commitments: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    next_step: str | None = None
    evidence: list[str] = Field(default_factory=list)
    task_title: str | None = None
    task_type: str = "follow_up"
    task_priority: CandidateTaskPriorityEnum = CandidateTaskPriorityEnum.MEDIUM
    task_due_at: datetime | None = None
