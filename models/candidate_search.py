import enum

from sqlalchemy import (
    BigInteger,
    Enum as SQLAlchemyEnum,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from . import BaseModel

class CandidateIndexEventTypeEnum(str, enum.Enum):
    """候选人索引事件类型。"""

    UPSERT = "upsert"
    DELETE = "delete"

class CandidateIndexEventStatusEnum(str, enum.Enum):
    """候选人索引事件处理状态。"""

    PENDING = "pending"
    PROCESSING = "processing"
    SUCCEEDED = "succeeded"
    FAILED = "failed"

class CandidateSearchProfileModel(BaseModel):
    """候选人语义检索画像。

    这张表保存的是 PostgreSQL 侧的“可检索事实快照”。
    Milvus 只是向量索引，真正的数据来源仍然以 PostgreSQL 为准。
    """

    __tablename__ = "candidate_search_profiles"

    candidate_id: Mapped[str] = mapped_column(
        ForeignKey("candidates.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )

    # 脱敏后的候选人画像文本，用于生成 embedding
    profile_text: Mapped[str] = mapped_column(Text, nullable=False)

    # 画像版本。候选人信息变化后递增，用于判断 Milvus 索引是否过期
    profile_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    # 后续生成 embedding 时记录模型名称
    embedding_model: Mapped[str | None] = mapped_column(String(128), nullable=True)

    # Milvus 写入成功后记录索引版本
    indexed_version: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # 最近一次索引错误信息，便于排查同步失败
    last_index_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    candidate = relationship("CandidateModel")

class CandidateIndexOutboxModel(BaseModel):
    """候选人索引同步事件。

    候选人新增、更新、删除时先写 outbox。
    后台任务再消费 outbox，调用 embedding 和 Milvus。
    """

    __tablename__ = "candidate_index_outbox"

    candidate_id: Mapped[str] = mapped_column(
        ForeignKey("candidates.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    event_type: Mapped[CandidateIndexEventTypeEnum] = mapped_column(
        SQLAlchemyEnum(
            CandidateIndexEventTypeEnum,
            values_callable=lambda obj: [e.value for e in obj],
        ),
        nullable=False,
    )

    status: Mapped[CandidateIndexEventStatusEnum] = mapped_column(
        SQLAlchemyEnum(
            CandidateIndexEventStatusEnum,
            values_callable=lambda obj: [e.value for e in obj],
        ),
        nullable=False,
        default=CandidateIndexEventStatusEnum.PENDING,
        index=True,
    )

    # 事件对应的画像版本。消费时可据此判断是否还有必要处理
    profile_version: Mapped[int] = mapped_column(Integer, nullable=False)

    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # 下次可重试时间，使用毫秒时间戳或秒时间戳都可以，保持项目内一致即可
    next_retry_at: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    candidate = relationship("CandidateModel")

    __table_args__ = (
        UniqueConstraint(
            "candidate_id",
            "event_type",
            "profile_version",
            name="uq_candidate_index_outbox_candidate_event_version",
        ),
    )