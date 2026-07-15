from models import Base
from models.knowledge import (
    KnowledgeBaseStatusEnum,
    KnowledgeDocumentStatusEnum,
    KnowledgeIndexTaskStatusEnum,
    KnowledgeIndexTaskTypeEnum,
)


def test_knowledge_models_register_complete_table_structure():
    """知识库四张业务表应被 Alembic 元数据发现。"""

    tables = Base.metadata.tables

    assert {
        "knowledge_bases",
        "knowledge_documents",
        "knowledge_document_chunks",
        "knowledge_index_tasks",
    }.issubset(tables)
    assert {"key", "collection_name", "schema_version", "retrieval_config"}.issubset(
        tables["knowledge_bases"].columns.keys()
    )
    assert {
        "knowledge_base_id",
        "storage_path",
        "content_hash",
        "visibility_scope",
    }.issubset(tables["knowledge_documents"].columns.keys())
    assert {
        "knowledge_base_id",
        "document_id",
        "chunk_index",
        "chunk_version",
        "section_path",
        "token_count",
    }.issubset(tables["knowledge_document_chunks"].columns.keys())
    assert {
        "idempotency_key",
        "knowledge_base_id",
        "document_id",
        "task_type",
        "status",
        "retry_count",
        "metadata",
    }.issubset(tables["knowledge_index_tasks"].columns.keys())


def test_knowledge_model_enums_cover_lifecycle_and_index_operations():
    """枚举值必须与迁移和后续任务消费者使用的稳定字符串一致。"""

    assert {item.value for item in KnowledgeBaseStatusEnum} == {"active", "archived"}
    assert {item.value for item in KnowledgeDocumentStatusEnum} == {
        "draft",
        "active",
        "archived",
        "index_failed",
    }
    assert {item.value for item in KnowledgeIndexTaskTypeEnum} == {
        "upsert",
        "delete",
        "rebuild",
    }
    assert {item.value for item in KnowledgeIndexTaskStatusEnum} == {
        "pending",
        "processing",
        "succeeded",
        "failed",
    }
