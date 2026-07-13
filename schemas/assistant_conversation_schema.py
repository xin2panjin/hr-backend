"""HR 招聘助手会话接口的请求与响应模型。"""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class CreateAssistantConversationReqSchema(BaseModel):
    """创建会话请求。"""

    title: str = Field(default="新对话", min_length=1, max_length=100)


class UpdateAssistantConversationReqSchema(BaseModel):
    """重命名、归档或恢复会话请求。"""

    title: str | None = Field(default=None, min_length=1, max_length=100)
    status: Literal["active", "archived"] | None = None


class AssistantConversationSchema(BaseModel):
    """会话列表项。"""

    id: str
    title: str
    status: str
    last_message_at: datetime
    created_at: datetime
    updated_at: datetime


class CreateAssistantConversationRespSchema(BaseModel):
    """创建会话响应，保持与技术设计文档的 ``conversation`` 包装一致。"""

    conversation: AssistantConversationSchema


class AssistantConversationListRespSchema(BaseModel):
    """分页会话列表。"""

    items: list[AssistantConversationSchema]
    total: int
    page: int
    size: int


class SendAssistantMessageReqSchema(BaseModel):
    """发送一条用户消息。"""

    content: str = Field(..., min_length=1, max_length=10_000)


class AssistantMessageSchema(BaseModel):
    """前端可回放的用户/助手消息。"""

    id: str
    role: str
    content: str
    artifacts: list[dict[str, Any]] = Field(default_factory=list)
    created_at: datetime


class AssistantMessageListRespSchema(BaseModel):
    """会话历史消息。"""

    items: list[AssistantMessageSchema]


class SendAssistantMessageRespSchema(BaseModel):
    """本轮对话的同步返回结果；后续可平滑替换为 SSE。"""

    conversation_id: str
    message_id: str
    answer: str
    artifacts: list[dict[str, Any]] = Field(default_factory=list)
