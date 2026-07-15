"""add knowledge base tables

Revision ID: n4o5p6q7r8s
Revises: m3n4o5p6q7r8
Create Date: 2026-07-14 12:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "n4o5p6q7r8s"
down_revision: Union[str, Sequence[str], None] = "m3n4o5p6q7r8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """创建通用知识库、文档、切片和索引任务表。"""

    op.create_table(
        "knowledge_bases",
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("collection_name", sa.String(length=128), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            sa.Enum("active", "archived", name="knowledgebasestatusenum"),
            nullable=False,
        ),
        sa.Column("retrieval_config", sa.JSON(), nullable=True),
        sa.Column("id", sa.String(length=100), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_knowledge_bases")),
        sa.UniqueConstraint("collection_name", name=op.f("uq_knowledge_bases_collection_name")),
    )
    op.create_index(op.f("ix_knowledge_bases_key"), "knowledge_bases", ["key"], unique=True)
    op.create_index(op.f("ix_knowledge_bases_status"), "knowledge_bases", ["status"], unique=False)

    op.create_table(
        "knowledge_documents",
        sa.Column("knowledge_base_id", sa.String(length=100), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("category", sa.String(length=64), nullable=True),
        sa.Column("storage_path", sa.String(length=500), nullable=False),
        sa.Column("file_name", sa.String(length=255), nullable=False),
        sa.Column("file_type", sa.String(length=32), nullable=False),
        sa.Column("version", sa.String(length=64), nullable=True),
        sa.Column("effective_date", sa.Date(), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "draft",
                "active",
                "archived",
                "index_failed",
                name="knowledgedocumentstatusenum",
            ),
            nullable=False,
        ),
        sa.Column("visibility_scope", sa.String(length=64), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("indexed_at", sa.DateTime(), nullable=True),
        sa.Column("created_by", sa.String(length=100), nullable=True),
        sa.Column("updated_by", sa.String(length=100), nullable=True),
        sa.Column("id", sa.String(length=100), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["knowledge_base_id"],
            ["knowledge_bases.id"],
            name=op.f("fk_knowledge_documents_knowledge_base_id_knowledge_bases"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name=op.f("fk_knowledge_documents_created_by_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["updated_by"],
            ["users.id"],
            name=op.f("fk_knowledge_documents_updated_by_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_knowledge_documents")),
    )
    op.create_index(op.f("ix_knowledge_documents_category"), "knowledge_documents", ["category"], unique=False)
    op.create_index(op.f("ix_knowledge_documents_content_hash"), "knowledge_documents", ["content_hash"], unique=False)
    op.create_index(op.f("ix_knowledge_documents_knowledge_base_id"), "knowledge_documents", ["knowledge_base_id"], unique=False)
    op.create_index(op.f("ix_knowledge_documents_status"), "knowledge_documents", ["status"], unique=False)
    op.create_index(op.f("ix_knowledge_documents_visibility_scope"), "knowledge_documents", ["visibility_scope"], unique=False)
    op.create_index(
        "ix_knowledge_document_base_status_effective",
        "knowledge_documents",
        ["knowledge_base_id", "status", "effective_date"],
        unique=False,
    )

    op.create_table(
        "knowledge_document_chunks",
        sa.Column("knowledge_base_id", sa.String(length=100), nullable=False),
        sa.Column("document_id", sa.String(length=100), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("chunk_version", sa.Integer(), nullable=False),
        sa.Column("section_path", sa.String(length=512), nullable=True),
        sa.Column("page_number", sa.Integer(), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("token_count", sa.Integer(), nullable=False),
        sa.Column("id", sa.String(length=100), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["knowledge_base_id"],
            ["knowledge_bases.id"],
            name=op.f("fk_knowledge_document_chunks_knowledge_base_id_knowledge_bases"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["knowledge_documents.id"],
            name=op.f("fk_knowledge_document_chunks_document_id_knowledge_documents"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_knowledge_document_chunks")),
        sa.UniqueConstraint(
            "document_id",
            "chunk_index",
            "chunk_version",
            name="uq_knowledge_document_chunk_document_index_version",
        ),
    )
    op.create_index(op.f("ix_knowledge_document_chunks_content_hash"), "knowledge_document_chunks", ["content_hash"], unique=False)
    op.create_index(op.f("ix_knowledge_document_chunks_document_id"), "knowledge_document_chunks", ["document_id"], unique=False)
    op.create_index(op.f("ix_knowledge_document_chunks_knowledge_base_id"), "knowledge_document_chunks", ["knowledge_base_id"], unique=False)
    op.create_index(
        "ix_knowledge_chunk_document_version_index",
        "knowledge_document_chunks",
        ["document_id", "chunk_version", "chunk_index"],
        unique=False,
    )

    op.create_table(
        "knowledge_index_tasks",
        sa.Column("knowledge_base_id", sa.String(length=100), nullable=False),
        sa.Column("document_id", sa.String(length=100), nullable=True),
        sa.Column(
            "task_type",
            sa.Enum("upsert", "delete", "rebuild", name="knowledgeindextasktypeenum"),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum(
                "pending",
                "processing",
                "succeeded",
                "failed",
                name="knowledgeindextaskstatusenum",
            ),
            nullable=False,
        ),
        sa.Column("content_hash", sa.String(length=64), nullable=True),
        sa.Column("target_chunk_version", sa.Integer(), nullable=True),
        sa.Column("retry_count", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=True),
        sa.Column("id", sa.String(length=100), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["knowledge_base_id"],
            ["knowledge_bases.id"],
            name=op.f("fk_knowledge_index_tasks_knowledge_base_id_knowledge_bases"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["knowledge_documents.id"],
            name=op.f("fk_knowledge_index_tasks_document_id_knowledge_documents"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_knowledge_index_tasks")),
    )
    op.create_index(op.f("ix_knowledge_index_tasks_document_id"), "knowledge_index_tasks", ["document_id"], unique=False)
    op.create_index(op.f("ix_knowledge_index_tasks_knowledge_base_id"), "knowledge_index_tasks", ["knowledge_base_id"], unique=False)
    op.create_index(op.f("ix_knowledge_index_tasks_status"), "knowledge_index_tasks", ["status"], unique=False)
    op.create_index(
        "ix_knowledge_index_task_pending",
        "knowledge_index_tasks",
        ["knowledge_base_id", "status", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    """删除通用知识库相关表。"""

    op.drop_index("ix_knowledge_index_task_pending", table_name="knowledge_index_tasks")
    op.drop_index(op.f("ix_knowledge_index_tasks_status"), table_name="knowledge_index_tasks")
    op.drop_index(op.f("ix_knowledge_index_tasks_knowledge_base_id"), table_name="knowledge_index_tasks")
    op.drop_index(op.f("ix_knowledge_index_tasks_document_id"), table_name="knowledge_index_tasks")
    op.drop_table("knowledge_index_tasks")

    op.drop_index("ix_knowledge_chunk_document_version_index", table_name="knowledge_document_chunks")
    op.drop_index(op.f("ix_knowledge_document_chunks_knowledge_base_id"), table_name="knowledge_document_chunks")
    op.drop_index(op.f("ix_knowledge_document_chunks_document_id"), table_name="knowledge_document_chunks")
    op.drop_index(op.f("ix_knowledge_document_chunks_content_hash"), table_name="knowledge_document_chunks")
    op.drop_table("knowledge_document_chunks")

    op.drop_index("ix_knowledge_document_base_status_effective", table_name="knowledge_documents")
    op.drop_index(op.f("ix_knowledge_documents_visibility_scope"), table_name="knowledge_documents")
    op.drop_index(op.f("ix_knowledge_documents_status"), table_name="knowledge_documents")
    op.drop_index(op.f("ix_knowledge_documents_knowledge_base_id"), table_name="knowledge_documents")
    op.drop_index(op.f("ix_knowledge_documents_content_hash"), table_name="knowledge_documents")
    op.drop_index(op.f("ix_knowledge_documents_category"), table_name="knowledge_documents")
    op.drop_table("knowledge_documents")

    op.drop_index(op.f("ix_knowledge_bases_status"), table_name="knowledge_bases")
    op.drop_index(op.f("ix_knowledge_bases_key"), table_name="knowledge_bases")
    op.drop_table("knowledge_bases")

    op.execute("DROP TYPE knowledgeindextaskstatusenum")
    op.execute("DROP TYPE knowledgeindextasktypeenum")
    op.execute("DROP TYPE knowledgedocumentstatusenum")
    op.execute("DROP TYPE knowledgebasestatusenum")
