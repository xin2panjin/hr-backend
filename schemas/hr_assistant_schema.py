from pydantic import BaseModel, Field


class HRAssistantChatReqSchema(BaseModel):
    message: str = Field(..., description="用户消息")
    conversation_id: str | None = Field(None, description="会话ID，不传则由后端生成")


class HRAssistantChatRespSchema(BaseModel):
    conversation_id: str
    answer: str