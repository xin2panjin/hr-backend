"""知识库检索策略运行时配置测试。"""

from types import SimpleNamespace

import pytest

from schemas.knowledge_schema import KnowledgeRetrievalConfigSchema
from services.knowledge_retrieval_config_service import (
    KnowledgeRetrievalConfigNotFoundError,
    KnowledgeRetrievalConfigService,
)


class FakeSession:
    def __init__(self, knowledge_base):
        self.knowledge_base = knowledge_base

    async def scalar(self, statement):
        return self.knowledge_base


@pytest.mark.asyncio
async def test_get_config_merges_defaults_for_existing_knowledge_base():
    knowledge_base = SimpleNamespace(
        retrieval_config={"retrieval_mode": "dense", "dense_recall_k": 12}
    )

    config = await KnowledgeRetrievalConfigService(session=FakeSession(knowledge_base)).get_config(
        knowledge_base_key="recruiting_policy"
    )

    assert config.retrieval_mode == "dense"
    assert config.dense_recall_k == 12
    assert config.rrf_k == 60
    assert config.rerank_enabled is False


@pytest.mark.asyncio
async def test_update_config_persists_validated_full_config():
    knowledge_base = SimpleNamespace(retrieval_config={})
    config = KnowledgeRetrievalConfigSchema(
        retrieval_mode="hybrid",
        dense_recall_k=30,
        sparse_recall_k=25,
        hybrid_limit=20,
        rrf_k=80,
        rerank_enabled=True,
        rerank_top_k=10,
        minimum_evidence_score=0.42,
        max_chunks_per_document=3,
        merge_adjacent_chunks=False,
    )

    result = await KnowledgeRetrievalConfigService(session=FakeSession(knowledge_base)).update_config(
        knowledge_base_key="recruiting_policy",
        config=config,
    )

    assert result == config
    assert knowledge_base.retrieval_config == config.model_dump()


@pytest.mark.asyncio
async def test_get_config_rejects_missing_or_archived_knowledge_base():
    with pytest.raises(KnowledgeRetrievalConfigNotFoundError):
        await KnowledgeRetrievalConfigService(session=FakeSession(None)).get_config(
            knowledge_base_key="recruiting_policy"
        )
