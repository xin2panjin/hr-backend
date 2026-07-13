import pytest

from rag.retrieval_types import RetrievalMode, RetrievalRequest, RetrievalSource
from rag.retrievers.milvus_hybrid_retriever import MilvusHybridRetriever


class FakeEmbeddingService:
    model = "fake-embedding"

    def __init__(self, vector_size=1024):
        self.vector_size = vector_size
        self.queries = []

    async def embed_query(self, query):
        self.queries.append(query)
        return [0.1] * self.vector_size


class FakeMilvusClient:
    def __init__(self):
        self.search_calls = []
        self.hybrid_calls = []

    def search(self, **kwargs):
        self.search_calls.append(kwargs)
        return [[self._build_hit("candidate-1", 0.91)]]

    def hybrid_search(self, **kwargs):
        self.hybrid_calls.append(kwargs)
        return [[self._build_hit("candidate-2", 0.76)]]

    @staticmethod
    def _build_hit(candidate_id, distance):
        return {
            "id": candidate_id,
            "distance": distance,
            "entity": {
                "candidate_id": candidate_id,
                "profile_text": "Python FastAPI Milvus",
                "position_id": "position-1",
                "department_id": "department-1",
                "creator_id": "creator-1",
                "status": "已投递",
                "profile_version": 2,
            },
        }


class SparseScoreMilvusClient(FakeMilvusClient):
    """返回不同 BM25 原始分数，用于验证对外展示分数的归一化。"""

    def search(self, **kwargs):
        self.search_calls.append(kwargs)
        return [[
            self._build_hit("candidate-1", 12.93),
            self._build_hit("candidate-2", 6.465),
        ]]


def build_request():
    return RetrievalRequest(
        query="Python FastAPI",
        filter_expression='department_id in ["department-1"]',
        dense_recall_k=12,
        sparse_recall_k=15,
        hybrid_limit=10,
    )


@pytest.mark.asyncio
async def test_dense_mode_builds_dense_vector_search():
    embedding_service = FakeEmbeddingService()
    milvus_client = FakeMilvusClient()
    retriever = MilvusHybridRetriever(
        embedding_service=embedding_service,
        milvus_client=milvus_client,
    )

    hits = await retriever.retrieve(build_request(), mode=RetrievalMode.DENSE)

    assert embedding_service.queries == ["Python FastAPI"]
    assert milvus_client.search_calls[0]["anns_field"] == "dense_vector"
    assert milvus_client.search_calls[0]["search_params"] == {"metric_type": "COSINE"}
    assert milvus_client.search_calls[0]["limit"] == 12
    assert milvus_client.search_calls[0]["filter"] == 'department_id in ["department-1"]'
    assert hits[0].candidate_id == "candidate-1"
    assert hits[0].rank_source == RetrievalSource.DENSE
    assert hits[0].metadata["profile_version"] == 2


@pytest.mark.asyncio
async def test_sparse_mode_uses_raw_query_without_embedding():
    embedding_service = FakeEmbeddingService()
    milvus_client = FakeMilvusClient()
    retriever = MilvusHybridRetriever(
        embedding_service=embedding_service,
        milvus_client=milvus_client,
    )

    hits = await retriever.retrieve(build_request(), mode="sparse")

    assert embedding_service.queries == []
    assert milvus_client.search_calls[0]["data"] == ["Python FastAPI"]
    assert milvus_client.search_calls[0]["anns_field"] == "sparse_vector"
    assert milvus_client.search_calls[0]["search_params"] == {"metric_type": "BM25"}
    assert milvus_client.search_calls[0]["limit"] == 15
    assert hits[0].rank_source == RetrievalSource.SPARSE


@pytest.mark.asyncio
async def test_sparse_mode_normalizes_bm25_scores_for_percentage_display():
    retriever = MilvusHybridRetriever(
        embedding_service=FakeEmbeddingService(),
        milvus_client=SparseScoreMilvusClient(),
    )

    hits = await retriever.retrieve(build_request(), mode=RetrievalMode.SPARSE)

    assert [hit.score for hit in hits] == [1.0, 0.5]
    assert [hit.metadata["raw_bm25_score"] for hit in hits] == [12.93, 6.465]


@pytest.mark.asyncio
async def test_hybrid_mode_builds_two_requests_with_same_filter():
    embedding_service = FakeEmbeddingService()
    milvus_client = FakeMilvusClient()
    retriever = MilvusHybridRetriever(
        embedding_service=embedding_service,
        milvus_client=milvus_client,
    )

    hits = await retriever.retrieve(build_request(), mode=RetrievalMode.HYBRID)

    call = milvus_client.hybrid_calls[0]
    dense_request, sparse_request = call["reqs"]
    assert embedding_service.queries == ["Python FastAPI"]
    assert dense_request.anns_field == "dense_vector"
    assert dense_request.param == {"metric_type": "COSINE"}
    assert dense_request.limit == 12
    assert sparse_request.anns_field == "sparse_vector"
    assert sparse_request.param == {"metric_type": "BM25"}
    assert sparse_request.limit == 15
    assert dense_request.filter == sparse_request.filter == 'department_id in ["department-1"]'
    assert type(call["ranker"]).__name__ == "RRFRanker"
    assert call["limit"] == 10
    assert hits[0].candidate_id == "candidate-2"
    assert hits[0].rank_source == RetrievalSource.HYBRID


@pytest.mark.asyncio
async def test_dense_mode_rejects_wrong_embedding_dimension():
    retriever = MilvusHybridRetriever(
        embedding_service=FakeEmbeddingService(vector_size=3),
        milvus_client=FakeMilvusClient(),
    )

    with pytest.raises(ValueError, match="Embedding维度不匹配"):
        await retriever.retrieve(build_request(), mode=RetrievalMode.DENSE)
