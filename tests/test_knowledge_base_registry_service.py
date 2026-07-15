"""知识库静态定义和初始化注册服务的测试。"""

from types import SimpleNamespace

import pytest

from knowledge.recruiting_policy import (
    RECRUITING_POLICY_KNOWLEDGE_BASE_KEY,
    build_recruiting_policy_knowledge_base_definition,
)
from services.knowledge_base_registry_service import KnowledgeBaseRegistryService


class FakeMilvusClient:
    """替代真实 Milvus，验证注册服务复用通用建表工厂。"""

    def __init__(self, existing_collections: set[str] | None = None):
        self.existing_collections = existing_collections or set()
        self.create_calls: list[dict] = []

    def has_collection(self, collection_name: str) -> bool:
        return collection_name in self.existing_collections

    def create_collection(self, **kwargs) -> None:
        self.create_calls.append(kwargs)


class FakeSession:
    """只模拟注册服务本阶段需要的数据库会话接口。"""

    def __init__(self, existing_knowledge_base=None):
        self.existing_knowledge_base = existing_knowledge_base
        self.added_models: list[object] = []

    async def scalar(self, statement):
        return self.existing_knowledge_base

    def add(self, model) -> None:
        self.added_models.append(model)


def test_recruiting_policy_definition_contains_required_schema_and_defaults():
    definition = build_recruiting_policy_knowledge_base_definition()

    assert definition.key == RECRUITING_POLICY_KNOWLEDGE_BASE_KEY
    assert definition.collection_name == "recruiting_policy_chunks_v1"
    assert definition.collection_definition.primary_key_field == "id"
    assert definition.collection_definition.text_field == "content"
    assert definition.collection_definition.vector_dim > 0
    assert {
        field.field_name for field in definition.collection_definition.metadata_fields
    } >= {
        "knowledge_base_id",
        "document_id",
        "title",
        "visibility_scope",
        "section_path",
        "chunk_index",
    }
    assert definition.retrieval_config["retrieval_mode"] == "hybrid"
    with pytest.raises(TypeError):
        definition.retrieval_config["hybrid_limit"] = 100


@pytest.mark.asyncio
async def test_registry_service_creates_collection_and_database_record():
    definition = build_recruiting_policy_knowledge_base_definition()
    session = FakeSession()
    milvus_client = FakeMilvusClient()

    result = await KnowledgeBaseRegistryService().ensure_registered(
        session=session,
        milvus_client=milvus_client,
        definition=definition,
    )

    assert result.collection_created is True
    assert result.database_record_created is True
    assert result.key == RECRUITING_POLICY_KNOWLEDGE_BASE_KEY
    assert milvus_client.create_calls[0]["collection_name"] == definition.collection_name
    created_model = session.added_models[0]
    assert created_model.key == definition.key
    assert created_model.collection_name == definition.collection_name
    assert created_model.retrieval_config == dict(definition.retrieval_config)


@pytest.mark.asyncio
async def test_registry_service_skips_matching_existing_registration():
    definition = build_recruiting_policy_knowledge_base_definition()
    existing_knowledge_base = SimpleNamespace(
        collection_name=definition.collection_name,
        schema_version=definition.schema_version,
        retrieval_config=dict(definition.retrieval_config),
    )
    session = FakeSession(existing_knowledge_base)
    milvus_client = FakeMilvusClient(existing_collections={definition.collection_name})

    result = await KnowledgeBaseRegistryService().ensure_registered(
        session=session,
        milvus_client=milvus_client,
        definition=definition,
    )

    assert result.collection_created is False
    assert result.database_record_created is False
    assert session.added_models == []


@pytest.mark.asyncio
async def test_registry_service_allows_runtime_retrieval_config_overrides():
    definition = build_recruiting_policy_knowledge_base_definition()
    existing_knowledge_base = SimpleNamespace(
        collection_name=definition.collection_name,
        schema_version=definition.schema_version,
        retrieval_config={**definition.retrieval_config, "rerank_enabled": True, "rrf_k": 80},
    )

    result = await KnowledgeBaseRegistryService().ensure_registered(
        session=FakeSession(existing_knowledge_base),
        milvus_client=FakeMilvusClient(existing_collections={definition.collection_name}),
        definition=definition,
    )

    assert result.database_record_created is False


@pytest.mark.asyncio
async def test_registry_service_rejects_mismatched_existing_registration():
    definition = build_recruiting_policy_knowledge_base_definition()
    existing_knowledge_base = SimpleNamespace(
        collection_name="wrong_collection",
        schema_version=definition.schema_version,
        retrieval_config=dict(definition.retrieval_config),
    )

    with pytest.raises(ValueError, match="collection_name"):
        await KnowledgeBaseRegistryService().ensure_registered(
            session=FakeSession(existing_knowledge_base),
            milvus_client=FakeMilvusClient(
                existing_collections={definition.collection_name}
            ),
            definition=definition,
        )
