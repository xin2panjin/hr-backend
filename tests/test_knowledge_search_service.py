"""制度知识库检索应用服务测试。"""

from dataclasses import dataclass, replace

import pytest

from knowledge.recruiting_policy import build_recruiting_policy_knowledge_base_definition
from rag.knowledge_sources import build_knowledge_sources
from rag.retrieval_types import RetrievalMode, SearchHit
from services.knowledge_search_service import KnowledgeSearchService


@dataclass
class FakeRetriever:
    """记录通用检索请求，避免测试访问真实 Embedding 和 Milvus。"""

    hits: list[SearchHit]
    request = None
    mode = None

    async def retrieve(self, request, *, mode):
        self.request = request
        self.mode = mode
        return list(self.hits)


@dataclass
class FakeReranker:
    """返回预设重排结果，验证服务不会调用真实云端模型。"""

    hits: list[SearchHit] | None = None
    error: Exception | None = None
    called = False

    async def rerank(self, *, query, hits, trace_id=None):
        self.called = True
        if self.error:
            raise self.error
        return list(self.hits if self.hits is not None else hits)


@pytest.mark.asyncio
async def test_search_builds_recruiting_policy_request_and_limits_results():
    retriever = FakeRetriever(
        hits=[
            SearchHit(
                entity_id="chunk-1",
                score=0.91,
                text="员工休假管理制度 > 年假\n年假申请规则",
                metadata={"document_id": "doc-1", "page_number": 3},
            ),
            SearchHit(entity_id="chunk-2", score=0.72, text="第二段", metadata={}),
        ]
    )
    service = KnowledgeSearchService(
        knowledge_base_definition=build_recruiting_policy_knowledge_base_definition(),
        retriever=retriever,
    )

    result = await service.search(query="  年假怎么申请  ", top_k=1, retrieval_mode="dense")

    assert result.knowledge_base_key == "recruiting_policy"
    assert result.retrieval_mode == RetrievalMode.DENSE
    assert result.hits[0].entity_id == "chunk-1"
    assert retriever.mode == RetrievalMode.DENSE
    assert retriever.request.query == "年假怎么申请"
    assert retriever.request.filter_expression == 'visibility_scope == "hr_only"'
    assert "content" in retriever.request.output_fields
    assert "title" in retriever.request.output_fields
    assert retriever.request.rrf_k == 60
    assert "page_number" in retriever.request.output_fields
    assert retriever.request.hybrid_limit >= 1


@pytest.mark.asyncio
async def test_search_allows_backend_filter_and_rejects_invalid_top_k():
    retriever = FakeRetriever(hits=[])
    service = KnowledgeSearchService(
        knowledge_base_definition=build_recruiting_policy_knowledge_base_definition(),
        retriever=retriever,
    )

    with pytest.raises(ValueError, match="top_k"):
        await service.search(query="试用期", top_k=0)

    await service.search(
        query="试用期",
        top_k=2,
        filter_expression='visibility_scope == "hr_only" and category == "onboarding"',
    )
    assert retriever.request.filter_expression.endswith('category == "onboarding"')


@pytest.mark.asyncio
async def test_search_escapes_visibility_scope_value():
    retriever = FakeRetriever(hits=[])
    service = KnowledgeSearchService(
        knowledge_base_definition=build_recruiting_policy_knowledge_base_definition(),
        retriever=retriever,
    )

    await service.search(query="入职", visibility_scope='hr"only')

    assert retriever.request.filter_expression == 'visibility_scope == "hr\\"only"'


@pytest.mark.asyncio
async def test_search_applies_configured_rerank_and_minimum_evidence_score():
    first = SearchHit(entity_id="chunk-1", score=0.2, text="弱匹配")
    second = SearchHit(entity_id="chunk-2", score=0.9, text="强匹配")
    definition = build_recruiting_policy_knowledge_base_definition()
    definition = replace(
        definition,
        retrieval_config={
            **definition.retrieval_config,
            "rerank_enabled": True,
            "rerank_top_k": 2,
            "minimum_evidence_score": 0.5,
        },
    )
    reranker = FakeReranker(hits=[second, first])
    service = KnowledgeSearchService(
        knowledge_base_definition=definition,
        retriever=FakeRetriever(hits=[first, second]),
        reranker=reranker,
    )

    result = await service.search(query="年假", top_k=2)

    assert reranker.called is True
    assert result.reranked is True
    assert [hit.entity_id for hit in result.hits] == ["chunk-2"]
    assert result.hits[0].score == 0.9


@pytest.mark.asyncio
async def test_search_keeps_retrieval_results_when_rerank_fails():
    definition = build_recruiting_policy_knowledge_base_definition()
    definition = replace(
        definition,
        retrieval_config={**definition.retrieval_config, "rerank_enabled": True},
    )
    retriever = FakeRetriever(
        hits=[SearchHit(entity_id="chunk-1", score=0.4, text="召回结果")]
    )
    service = KnowledgeSearchService(
        knowledge_base_definition=definition,
        retriever=retriever,
        reranker=FakeReranker(error=RuntimeError("模型超时")),
    )

    result = await service.search(query="试用期", top_k=1)

    assert result.reranked is False
    assert [hit.entity_id for hit in result.hits] == ["chunk-1"]


def test_organize_hits_deduplicates_and_merges_adjacent_chunks():
    hits = [
        SearchHit(
            entity_id="chunk-2",
            score=0.91,
            text="第二段正文",
            metadata={
                "document_id": "doc-1",
                "chunk_version": 1,
                "chunk_index": 2,
                "section_path": "年假",
                "page_number": 3,
            },
        ),
        SearchHit(
            entity_id="chunk-1",
            score=0.85,
            text="第一段正文",
            metadata={
                "document_id": "doc-1",
                "chunk_version": 1,
                "chunk_index": 1,
                "section_path": "年假",
                "page_number": 2,
            },
        ),
        SearchHit(
            entity_id="chunk-1",
            score=0.80,
            text="重复命中",
            metadata={"document_id": "doc-1", "chunk_index": 1},
        ),
    ]

    result = KnowledgeSearchService._organize_hits(
        hits,
        top_k=5,
        max_chunks_per_document=2,
        merge_adjacent_chunks=True,
    )

    assert len(result) == 1
    assert result[0].entity_id == "chunk-1"
    assert result[0].text == "第一段正文\n第二段正文"
    assert result[0].metadata["merged_chunk_ids"] == ["chunk-1", "chunk-2"]
    assert result[0].metadata["page_number"] == 2
    assert result[0].metadata["page_end"] == 3


def test_organize_hits_limits_non_adjacent_chunks_per_document():
    hits = [
        SearchHit(
            entity_id=f"chunk-{index}",
            score=1.0 - index / 10,
            text=f"正文 {index}",
            metadata={
                "document_id": "doc-1",
                "chunk_version": 1,
                "chunk_index": index,
                "section_path": "年假",
            },
        )
        for index in (1, 3, 5)
    ]

    result = KnowledgeSearchService._organize_hits(
        hits,
        top_k=5,
        max_chunks_per_document=2,
        merge_adjacent_chunks=True,
    )

    assert [hit.entity_id for hit in result] == ["chunk-1", "chunk-3"]


def test_organize_hits_does_not_merge_different_sections():
    hits = [
        SearchHit(
            entity_id="chunk-1",
            score=0.9,
            text="年假正文",
            metadata={"document_id": "doc-1", "chunk_index": 1, "section_path": "年假"},
        ),
        SearchHit(
            entity_id="chunk-2",
            score=0.8,
            text="病假正文",
            metadata={"document_id": "doc-1", "chunk_index": 2, "section_path": "病假"},
        ),
    ]

    result = KnowledgeSearchService._organize_hits(
        hits,
        top_k=5,
        max_chunks_per_document=2,
        merge_adjacent_chunks=True,
    )

    assert [hit.entity_id for hit in result] == ["chunk-1", "chunk-2"]


def test_build_knowledge_sources_preserves_citation_fields_and_merged_ids():
    hit = SearchHit(
        entity_id="chunk-1",
        score=0.88,
        text="员工年假规则",
        metadata={
            "document_id": "doc-1",
            "title": "员工休假管理制度",
            "version": "V2",
            "section_path": "第三章 > 年假",
            "page_number": 5,
            "page_end": 6,
            "merged_chunk_ids": ["chunk-1", "chunk-2"],
        },
    )

    source = build_knowledge_sources([hit])[0]

    assert source.to_dict() == {
        "source_id": "chunk-1",
        "document_id": "doc-1",
        "title": "员工休假管理制度",
        "version": "V2",
        "section_path": "第三章 > 年假",
        "page_number": 5,
        "page_end": 6,
        "score": 0.88,
        "content": "员工年假规则",
        "chunk_ids": ["chunk-1", "chunk-2"],
    }
