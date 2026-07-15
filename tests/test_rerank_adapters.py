import pytest

from rag.rerankers import (
    CohereCompatibleReranker,
    DashScopeNativeReranker,
    NoopReranker,
)
from rag.retrieval_types import RetrievalSource, SearchHit


def build_hits():
    return [
        SearchHit(
            entity_id="candidate-1",
            score=0.03,
            text="Python 后端和知识库问答经验",
            rank_source=RetrievalSource.HYBRID,
        ),
        SearchHit(
            entity_id="candidate-2",
            score=0.02,
            text="FastAPI 与 Milvus 项目经验",
            rank_source=RetrievalSource.HYBRID,
        ),
    ]


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class FakeHTTPClient:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    async def post(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return FakeResponse(self.payload)


@pytest.mark.asyncio
async def test_noop_reranker_keeps_input_order_without_mutating_list():
    hits = build_hits()

    result = await NoopReranker().rerank(query="Python", hits=hits)

    assert result == hits
    assert result is not hits


@pytest.mark.asyncio
async def test_cohere_compatible_adapter_reorders_by_api_relevance_score():
    client = FakeHTTPClient(
        {
            "results": [
                {"index": 1, "relevance_score": 0.94},
                {"index": 0, "relevance_score": 0.71},
            ]
        }
    )
    reranker = CohereCompatibleReranker(
        model="qwen3-rerank",
        base_url="https://example.com/reranks",
        api_key="test-key",
        max_profile_chars=1,
        client=client,
    )

    result = await reranker.rerank(query="找 Milvus 工程师", hits=build_hits())

    assert [hit.entity_id for hit in result] == ["candidate-2", "candidate-1"]
    assert result[0].score == 0.94
    assert client.calls[0][1]["json"] == {
        "model": "qwen3-rerank",
        "query": "找 Milvus 工程师",
        "documents": ["P", "F"],
        "top_n": 2,
    }
    assert client.calls[0][1]["headers"]["Authorization"] == "Bearer test-key"


@pytest.mark.asyncio
async def test_dashscope_native_adapter_supports_nested_protocol():
    client = FakeHTTPClient(
        {
            "output": {
                "results": [
                    {"index": 0, "relevance_score": 0.87},
                    {"index": 1, "relevance_score": 0.31},
                ]
            }
        }
    )
    reranker = DashScopeNativeReranker(
        model="bge-reranker-v2-m3",
        base_url="https://example.com/text-rerank",
        api_key="test-key",
        client=client,
    )

    result = await reranker.rerank(query="Python", hits=build_hits())

    assert [hit.entity_id for hit in result] == ["candidate-1", "candidate-2"]
    assert client.calls[0][1]["json"] == {
        "model": "bge-reranker-v2-m3",
        "input": {
            "query": "Python",
            "documents": ["Python 后端和知识库问答经验", "FastAPI 与 Milvus 项目经验"],
        },
        "parameters": {"top_n": 2, "return_documents": False},
    }
