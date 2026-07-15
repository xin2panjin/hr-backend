import pytest

from rag.retrieval_types import (
    RetrievalHit,
    RetrievalMode,
    RetrievalRequest,
    RetrievalSource,
    SearchHit,
    SearchRequest,
    deduplicate_hits,
    deduplicate_search_hits,
)


def test_retrieval_request_normalizes_query_and_keeps_filter():
    request = RetrievalRequest(
        query="  查找 Python 后端工程师  ",
        filter_expression='status == "APPLICATION"',
        dense_recall_k=20,
        sparse_recall_k=20,
        hybrid_limit=15,
    )

    assert request.query == "查找 Python 后端工程师"
    assert request.filter_expression == 'status == "APPLICATION"'
    assert request.hybrid_limit == 15


def test_retrieval_request_rejects_invalid_input():
    with pytest.raises(ValueError, match="检索问题不能为空"):
        RetrievalRequest(query="   ")

    with pytest.raises(ValueError, match="检索数量必须大于 0"):
        RetrievalRequest(query="Python", dense_recall_k=0)


def test_search_request_uses_generic_output_fields():
    request = SearchRequest(
        query="  年假如何计算  ",
        output_fields=("chunk_id", "content", "document_id"),
    )

    assert request.query == "年假如何计算"
    assert request.output_fields == ("chunk_id", "content", "document_id")


def test_search_hit_converts_to_candidate_compatibility_contract():
    search_hit = SearchHit(
        entity_id="chunk-1",
        score=0.91,
        text="年假规则",
        metadata={"document_id": "leave-policy-v1"},
        rank_source=RetrievalSource.DENSE,
    )

    candidate_hit = RetrievalHit.from_search_hit(search_hit)

    assert candidate_hit.candidate_id == "chunk-1"
    assert candidate_hit.profile_text == "年假规则"
    assert candidate_hit.to_search_hit() == search_hit


def test_deduplicate_search_hits_keeps_first_ranked_entity():
    hits = [
        SearchHit(entity_id="chunk-1", score=0.9, text="第一段"),
        SearchHit(entity_id="chunk-1", score=0.7, text="重复段"),
        SearchHit(entity_id="chunk-2", score=0.6, text="第二段"),
    ]

    result = deduplicate_search_hits(hits)

    assert [hit.entity_id for hit in result] == ["chunk-1", "chunk-2"]
    assert result[0].to_dict()["text"] == "第一段"


def test_deduplicate_hits_keeps_first_ranked_candidate():
    hits = [
        RetrievalHit(
            candidate_id="candidate-1",
            score=0.98,
            profile_text="Python FastAPI",
            rank_source=RetrievalSource.HYBRID,
        ),
        RetrievalHit(
            candidate_id="candidate-1",
            score=0.80,
            profile_text="Python FastAPI",
            rank_source=RetrievalSource.SPARSE,
        ),
        RetrievalHit(
            candidate_id="candidate-2",
            score=0.75,
            profile_text="风控平台",
            rank_source=RetrievalSource.DENSE,
        ),
    ]

    result = deduplicate_hits(hits)

    assert [hit.candidate_id for hit in result] == [
        "candidate-1",
        "candidate-2",
    ]
    assert result[0].score == 0.98
    assert result[0].to_dict()["rank_source"] == "hybrid"


def test_retrieval_mode_has_three_supported_values():
    """检索模式应与 Milvus 的三种召回方式一一对应。"""

    assert {mode.value for mode in RetrievalMode} == {"dense", "sparse", "hybrid"}
