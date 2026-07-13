"""HR 招聘助手会话的业务数据模型。

LangGraph checkpoint 用于恢复 Agent 的运行状态；本模块中的表用于会话列表、
历史展示、权限校验和业务审计。两者职责互补，不能互相替代。
"""

import enum
from datetime import datetime

from sqlalchemy import DateTime, Enum as SQLAlchemyEnum, ForeignKey, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from . import BaseModel


class AssistantConversationStatusEnum(str, enum.Enum):
    """会话生命周期状态。"""

    ACTIVE = "active"
    ARCHIVED = "archived"
    DELETED = "deleted"


class AssistantMessageRoleEnum(str, enum.Enum):
    """业务消息的来源角色，不保存模型内部推理过程。"""

    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class AssistantConversationModel(BaseModel):
    """HR 招聘助手会话。

    ``id`` 是业务会话 ID；调用 LangGraph 时由应用层将其组装为稳定的
    thread_id，防止不同用户使用同一个会话 ID 时发生上下文串扰。
    """

    __tablename__ = "assistant_conversations"

    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(100), nullable=False, default="新对话")
    status: Mapped[AssistantConversationStatusEnum] = mapped_column(
        SQLAlchemyEnum(
            AssistantConversationStatusEnum,
            values_callable=lambda obj: [item.value for item in obj],
        ),
        nullable=False,
        default=AssistantConversationStatusEnum.ACTIVE,
        index=True,
    )
    last_message_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=datetime.now,
        index=True,
    )

    user = relationship("UserModel")
    messages = relationship(
        "AssistantMessageModel",
        back_populates="conversation",
        cascade="all, delete-orphan",
    )


class AssistantMessageModel(BaseModel):
    """助手会话的业务消息和工具调用摘要。"""

    __tablename__ = "assistant_messages"

    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("assistant_conversations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role: Mapped[AssistantMessageRoleEnum] = mapped_column(
        SQLAlchemyEnum(
            AssistantMessageRoleEnum,
            values_callable=lambda obj: [item.value for item in obj],
        ),
        nullable=False,
        index=True,
    )
    # 对 USER / ASSISTANT 是可展示正文；TOOL 只写脱敏后的摘要。
    content: Mapped[str] = mapped_column(Text, nullable=False)
    tool_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # 保存前端回放所需的工具产物；不保存模型内部推理过程。
    message_metadata: Mapped[dict | None] = mapped_column("metadata", JSON, nullable=True)

    conversation = relationship("AssistantConversationModel", back_populates="messages")
