import pytest

from rag.retrieval_types import (
    RetrievalMode,
    RetrievalRequest,
    RetrievalSource,
    SearchRequest,
)
from rag.retrievers.milvus_hybrid_retriever import (
    MilvusCollectionSchema,
    MilvusHybridRetriever,
)


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


class KnowledgeMilvusClient(FakeMilvusClient):
    """模拟字段名不同于候选人画像的知识库 Collection。"""

    def search(self, **kwargs):
        self.search_calls.append(kwargs)
        return [[self._build_hit("chunk-1", 0.88)]]

    @staticmethod
    def _build_hit(chunk_id, distance):
        return {
            "id": chunk_id,
            "distance": distance,
            "entity": {
                "chunk_id": chunk_id,
                "content": "第三章 年假规则：工作满一年可享受年休假。",
                "document_id": "leave-policy-v1",
                "section_path": "第三章 > 年假规则",
            },
        }


def build_request():
    return RetrievalRequest(
        query="Python FastAPI",
        filter_expression='department_id in ["department-1"]',
        dense_recall_k=12,
        sparse_recall_k=15,
        hybrid_limit=10,
        rrf_k=80,
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
    assert hits[0].entity_id == "candidate-1"
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
    assert call["ranker"].dict()["params"]["k"] == 80
    assert call["limit"] == 10
    assert hits[0].entity_id == "candidate-2"
    assert hits[0].rank_source == RetrievalSource.HYBRID


@pytest.mark.asyncio
async def test_dense_mode_rejects_wrong_embedding_dimension():
    retriever = MilvusHybridRetriever(
        embedding_service=FakeEmbeddingService(vector_size=3),
        milvus_client=FakeMilvusClient(),
    )

    with pytest.raises(ValueError, match="Embedding维度不匹配"):
        await retriever.retrieve(build_request(), mode=RetrievalMode.DENSE)


@pytest.mark.asyncio
async def test_custom_collection_schema_controls_milvus_fields_and_result_mapping():
    """非候选人 Collection 可复用同一召回器，且不读取候选人固定字段。"""

    schema = MilvusCollectionSchema(
        collection_name="recruiting_policy_chunks_v1",
        primary_key_field="chunk_id",
        text_field="content",
        vector_dim=4,
    )
    milvus_client = KnowledgeMilvusClient()
    retriever = MilvusHybridRetriever(
        embedding_service=FakeEmbeddingService(vector_size=4),
        milvus_client=milvus_client,
        collection_schema=schema,
    )
    request = SearchRequest(
        query="年假如何计算",
        output_fields=("chunk_id", "content", "document_id", "section_path"),
    )

    hits = await retriever.retrieve(request, mode=RetrievalMode.DENSE)

    call = milvus_client.search_calls[0]
    assert call["collection_name"] == "recruiting_policy_chunks_v1"
    assert call["anns_field"] == "dense_vector"
    assert call["output_fields"] == ["chunk_id", "content", "document_id", "section_path"]
    assert hits[0].entity_id == "chunk-1"
    assert hits[0].text == "第三章 年假规则：工作满一年可享受年休假。"
    assert hits[0].metadata == {
        "document_id": "leave-policy-v1",
        "section_path": "第三章 > 年假规则",
    }
