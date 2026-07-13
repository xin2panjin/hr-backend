import pytest

from rag.retrieval_types import (
    RetrievalHit,
    RetrievalMode,
    RetrievalRequest,
    RetrievalSource,
    deduplicate_hits,
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
