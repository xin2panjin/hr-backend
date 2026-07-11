from typing import Any, Literal

from pydantic import BaseModel, Field


class HRAssistantChatReqSchema(BaseModel):
    message: str = Field(..., description="用户消息")
    conversation_id: str | None = Field(None, description="会话ID，不传则由后端生成")


class HRAssistantCandidateActionSchema(BaseModel):
    """前端候选人卡片可执行动作。"""

    type: Literal["open_candidate_detail"] = Field(..., description="动作类型")
    label: str = Field(..., description="动作展示文案")
    candidate_id: str = Field(..., description="候选人ID")


class HRAssistantCandidateCardSchema(BaseModel):
    """HR助手返回给前端渲染的候选人卡片数据。"""

    candidate_id: str
    name: str | None = None
    position_title: str | None = None
    status: str | None = None
    score: float | None = None
    summary: str | None = None
    actions: list[HRAssistantCandidateActionSchema] = Field(default_factory=list)


class HRAssistantArtifactSchema(BaseModel):
    """HR助手结构化产物。

    前端后续可以根据 type 决定渲染成候选人卡片、候选人详情卡片或对比表格。
    """

    type: Literal["candidate_cards", "candidate_detail", "candidate_comparison"]
    title: str
    candidates: list[HRAssistantCandidateCardSchema] = Field(default_factory=list)
    raw: dict[str, Any] | None = Field(None, description="保留原始工具结果，便于后续扩展")


class HRAssistantChatRespSchema(BaseModel):
    conversation_id: str
    answer: str
    artifacts: list[HRAssistantArtifactSchema] = Field(default_factory=list)