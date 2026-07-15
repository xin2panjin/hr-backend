"""通用知识库的业务数据模型。

Milvus 只保存可检索切片和向量；本模块保存知识库配置、原始文档元数据、
切片审计信息和索引任务状态，作为后续制度、客服等业务场景的事实来源。
"""

import enum
from datetime import date, datetime

from sqlalchemy import (
    Date,
    DateTime,
    Enum as SQLAlchemyEnum,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from . import BaseModel


class KnowledgeBaseStatusEnum(str, enum.Enum):
    """知识库生命周期状态。"""

    ACTIVE = "active"
    ARCHIVED = "archived"


class KnowledgeDocumentStatusEnum(str, enum.Enum):
    """文档在知识库中的可检索状态。"""

    DRAFT = "draft"
    ACTIVE = "active"
    ARCHIVED = "archived"
    INDEX_FAILED = "index_failed"


class KnowledgeIndexTaskTypeEnum(str, enum.Enum):
    """索引任务的业务动作。"""

    UPSERT = "upsert"
    DELETE = "delete"
    REBUILD = "rebuild"


class KnowledgeIndexTaskStatusEnum(str, enum.Enum):
    """索引任务处理状态。"""

    PENDING = "pending"
    PROCESSING = "processing"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class KnowledgeBaseModel(BaseModel):
    """一个受后端注册和管理的独立知识库。"""

    __tablename__ = "knowledge_bases"

    # key 是业务侧的稳定标识，例如 recruiting_policy；不能由客户端随意指定。
    key: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    collection_name: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        unique=True,
    )
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[KnowledgeBaseStatusEnum] = mapped_column(
        SQLAlchemyEnum(
            KnowledgeBaseStatusEnum,
            name="knowledgebasestatusenum",
            values_callable=lambda obj: [item.value for item in obj],
        ),
        nullable=False,
        default=KnowledgeBaseStatusEnum.ACTIVE,
        index=True,
    )
    # 只记录可审计的检索参数快照，密钥仍由 .env 管理。
    retrieval_config: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    documents = relationship(
        "KnowledgeDocumentModel",
        back_populates="knowledge_base",
        cascade="all, delete-orphan",
    )
    index_tasks = relationship(
        "KnowledgeIndexTaskModel",
        back_populates="knowledge_base",
        cascade="all, delete-orphan",
    )


class KnowledgeDocumentModel(BaseModel):
    """知识库中的原始文档及其索引状态。"""

    __tablename__ = "knowledge_documents"

    knowledge_base_id: Mapped[str] = mapped_column(
        ForeignKey("knowledge_bases.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    category: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    storage_path: Mapped[str] = mapped_column(String(500), nullable=False)
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    file_type: Mapped[str] = mapped_column(String(32), nullable=False)
    version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    effective_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[KnowledgeDocumentStatusEnum] = mapped_column(
        SQLAlchemyEnum(
            KnowledgeDocumentStatusEnum,
            name="knowledgedocumentstatusenum",
            values_callable=lambda obj: [item.value for item in obj],
        ),
        nullable=False,
        default=KnowledgeDocumentStatusEnum.DRAFT,
        index=True,
    )
    visibility_scope: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default="hr_only",
        index=True,
    )
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    indexed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_by: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    updated_by: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    knowledge_base = relationship("KnowledgeBaseModel", back_populates="documents")
    chunks = relationship(
        "KnowledgeDocumentChunkModel",
        back_populates="document",
        cascade="all, delete-orphan",
    )
    index_tasks = relationship(
        "KnowledgeIndexTaskModel",
        back_populates="document",
        cascade="all, delete-orphan",
    )


class KnowledgeDocumentChunkModel(BaseModel):
    """文档结构化切片的 PostgreSQL 审计记录。"""

    __tablename__ = "knowledge_document_chunks"

    knowledge_base_id: Mapped[str] = mapped_column(
        ForeignKey("knowledge_bases.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    document_id: Mapped[str] = mapped_column(
        ForeignKey("knowledge_documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    chunk_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    section_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    page_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    token_count: Mapped[int] = mapped_column(Integer, nullable=False)

    knowledge_base = relationship("KnowledgeBaseModel")
    document = relationship("KnowledgeDocumentModel", back_populates="chunks")

    __table_args__ = (
        UniqueConstraint(
            "document_id",
            "chunk_index",
            "chunk_version",
            name="uq_knowledge_document_chunk_document_index_version",
        ),
    )


class KnowledgeIndexTaskModel(BaseModel):
    """文档解析、切片、Embedding 与 Milvus 写入的异步任务记录。"""

    __tablename__ = "knowledge_index_tasks"

    # 同一文档、内容版本和任务动作重复提交时复用同一条任务，保证幂等。
    idempotency_key: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        unique=True,
    )
    knowledge_base_id: Mapped[str] = mapped_column(
        ForeignKey("knowledge_bases.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # 文档删除后任务无需保留；后续全量对账任务可不绑定具体文档。
    document_id: Mapped[str | None] = mapped_column(
        ForeignKey("knowledge_documents.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    task_type: Mapped[KnowledgeIndexTaskTypeEnum] = mapped_column(
        SQLAlchemyEnum(
            KnowledgeIndexTaskTypeEnum,
            name="knowledgeindextasktypeenum",
            values_callable=lambda obj: [item.value for item in obj],
        ),
        nullable=False,
    )
    status: Mapped[KnowledgeIndexTaskStatusEnum] = mapped_column(
        SQLAlchemyEnum(
            KnowledgeIndexTaskStatusEnum,
            name="knowledgeindextaskstatusenum",
            values_callable=lambda obj: [item.value for item in obj],
        ),
        nullable=False,
        default=KnowledgeIndexTaskStatusEnum.PENDING,
        index=True,
    )
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    target_chunk_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    task_metadata: Mapped[dict | None] = mapped_column("metadata", JSON, nullable=True)

    knowledge_base = relationship("KnowledgeBaseModel", back_populates="index_tasks")
    document = relationship("KnowledgeDocumentModel", back_populates="index_tasks")
