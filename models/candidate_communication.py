"""候选人沟通、AI 洞察与 HR 待办的业务模型。"""

import enum
from datetime import datetime

from sqlalchemy import DateTime, Enum as SQLAlchemyEnum, ForeignKey, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from . import BaseModel


class CandidateMessageSenderEnum(str, enum.Enum):
    CANDIDATE = "candidate"
    HR = "hr"


class CandidateInsightOutboxStatusEnum(str, enum.Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class CandidateFollowupTaskStatusEnum(str, enum.Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class CandidateTaskPriorityEnum(str, enum.Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class CandidateConversationModel(BaseModel):
    """一个候选人投递记录对应一条独立沟通会话。"""

    __tablename__ = "candidate_conversations"

    candidate_id: Mapped[str] = mapped_column(
        ForeignKey("candidates.id", ondelete="CASCADE"), nullable=False, unique=True, index=True
    )
    owner_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    last_message_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.now, index=True)

    candidate = relationship("CandidateModel")
    owner = relationship("UserModel", foreign_keys=[owner_id])
    messages = relationship("CandidateConversationMessageModel", back_populates="conversation", cascade="all, delete-orphan")


class CandidateConversationMessageModel(BaseModel):
    __tablename__ = "candidate_conversation_messages"

    conversation_id: Mapped[str] = mapped_column(ForeignKey("candidate_conversations.id", ondelete="CASCADE"), nullable=False, index=True)
    sender_type: Mapped[CandidateMessageSenderEnum] = mapped_column(
        SQLAlchemyEnum(CandidateMessageSenderEnum, values_callable=lambda obj: [item.value for item in obj]), nullable=False
    )
    sender_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)

    conversation = relationship("CandidateConversationModel", back_populates="messages")
    sender_user = relationship("UserModel")


class CandidateConversationReadStateModel(BaseModel):
    __tablename__ = "candidate_conversation_read_states"
    __table_args__ = (UniqueConstraint("conversation_id", "user_id", name="uq_candidate_conversation_read_state"),)

    conversation_id: Mapped[str] = mapped_column(ForeignKey("candidate_conversations.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    last_read_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.now)


class CandidateConversationInsightModel(BaseModel):
    """洞察为不可变快照，便于追溯 AI 判断及其证据。"""

    __tablename__ = "candidate_conversation_insights"

    conversation_id: Mapped[str] = mapped_column(ForeignKey("candidate_conversations.id", ondelete="CASCADE"), nullable=False, index=True)
    source_message_id: Mapped[str] = mapped_column(ForeignKey("candidate_conversation_messages.id", ondelete="CASCADE"), nullable=False, unique=True)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    stage: Mapped[str | None] = mapped_column(String(50), nullable=True)
    intent: Mapped[str | None] = mapped_column(String(100), nullable=True)
    confirmed_facts: Mapped[list | None] = mapped_column(JSON, nullable=True)
    candidate_requests: Mapped[list | None] = mapped_column(JSON, nullable=True)
    hr_commitments: Mapped[list | None] = mapped_column(JSON, nullable=True)
    risks: Mapped[list | None] = mapped_column(JSON, nullable=True)
    next_step: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence: Mapped[list | None] = mapped_column(JSON, nullable=True)


class CandidateInsightOutboxModel(BaseModel):
    __tablename__ = "candidate_insight_outbox"

    source_message_id: Mapped[str] = mapped_column(ForeignKey("candidate_conversation_messages.id", ondelete="CASCADE"), nullable=False, unique=True)
    status: Mapped[CandidateInsightOutboxStatusEnum] = mapped_column(
        SQLAlchemyEnum(CandidateInsightOutboxStatusEnum, values_callable=lambda obj: [item.value for item in obj]),
        nullable=False, default=CandidateInsightOutboxStatusEnum.PENDING, index=True,
    )
    attempts: Mapped[int] = mapped_column(nullable=False, default=0)
    # 候选人最后一条消息后的静默窗口结束时间；到期前绝不调用洞察模型。
    available_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class CandidateFollowupTaskModel(BaseModel):
    __tablename__ = "candidate_followup_tasks"

    conversation_id: Mapped[str] = mapped_column(ForeignKey("candidate_conversations.id", ondelete="CASCADE"), nullable=False, index=True)
    candidate_id: Mapped[str] = mapped_column(ForeignKey("candidates.id", ondelete="CASCADE"), nullable=False, index=True)
    assignee_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    source_outbox_id: Mapped[str | None] = mapped_column(ForeignKey("candidate_insight_outbox.id", ondelete="SET NULL"), nullable=True, unique=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    task_type: Mapped[str] = mapped_column(String(50), nullable=False, default="follow_up")
    priority: Mapped[CandidateTaskPriorityEnum] = mapped_column(
        SQLAlchemyEnum(CandidateTaskPriorityEnum, values_callable=lambda obj: [item.value for item in obj]), nullable=False, default=CandidateTaskPriorityEnum.MEDIUM
    )
    status: Mapped[CandidateFollowupTaskStatusEnum] = mapped_column(
        SQLAlchemyEnum(CandidateFollowupTaskStatusEnum, values_callable=lambda obj: [item.value for item in obj]), nullable=False, default=CandidateFollowupTaskStatusEnum.PENDING, index=True
    )
    due_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    evidence: Mapped[list | None] = mapped_column(JSON, nullable=True)

    conversation = relationship("CandidateConversationModel")
    candidate = relationship("CandidateModel")
    assignee = relationship("UserModel", foreign_keys=[assignee_id])


class CandidateFollowupTaskNoteModel(BaseModel):
    __tablename__ = "candidate_followup_task_notes"

    task_id: Mapped[str] = mapped_column(ForeignKey("candidate_followup_tasks.id", ondelete="CASCADE"), nullable=False, index=True)
    author_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    task = relationship("CandidateFollowupTaskModel")
    author = relationship("UserModel")
