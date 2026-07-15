"""Milvus 稠密、BM25 稀疏与混合检索实现。"""

from dataclasses import dataclass, replace
from typing import Any

from pymilvus import AnnSearchRequest, RRFRanker

from rag.embeddings import EmbeddingService
from rag.milvus_client import get_milvus_client
from rag.retrieval_types import (
    RetrievalMode,
    RetrievalSource,
    SearchHit,
    SearchRequest,
    deduplicate_search_hits,
)
from settings import settings


@dataclass(frozen=True, slots=True)
class MilvusCollectionSchema:
    """一次 Milvus 检索所需的 Collection 与字段映射。

    Retriever 只依赖这份结构，不感知候选人、制度或未来其他业务的
    具体字段命名。业务层负责创建受控的 Schema，不能由接口参数直接传入。
    """

    collection_name: str
    primary_key_field: str
    text_field: str
    vector_dim: int
    dense_vector_field: str = "dense_vector"
    sparse_vector_field: str = "sparse_vector"

    def __post_init__(self) -> None:
        for field_name, value in (
            ("collection_name", self.collection_name),
            ("primary_key_field", self.primary_key_field),
            ("text_field", self.text_field),
            ("dense_vector_field", self.dense_vector_field),
            ("sparse_vector_field", self.sparse_vector_field),
        ):
            if not value.strip():
                raise ValueError(f"{field_name} 不能为空")
        if self.vector_dim < 1:
            raise ValueError("vector_dim 必须大于 0")


def build_candidate_collection_schema() -> MilvusCollectionSchema:
    """构造候选人画像的固定 Schema，集中保留候选人侧配置。"""

    return MilvusCollectionSchema(
        collection_name=settings.MILVUS_CANDIDATE_COLLECTION,
        primary_key_field="candidate_id",
        text_field="profile_text",
        vector_dim=settings.MILVUS_CANDIDATE_VECTOR_DIM,
    )


class MilvusHybridRetriever:
    """将 Milvus 的多种召回方式转换为通用 ``SearchHit``。

    本类只处理向量检索请求和命中结果转换；权限过滤表达式由调用方传入，
    PostgreSQL 权限复核和业务详情补全仍由各业务 Service 负责。
    """

    def __init__(
        self,
        *,
        embedding_service: EmbeddingService | None = None,
        milvus_client=None,
        collection_schema: MilvusCollectionSchema | None = None,
    ):
        self.embedding_service = embedding_service or EmbeddingService()
        self.milvus_client = milvus_client or get_milvus_client()
        # 保留候选人 Schema 作为兼容默认值，现有调用方无需立即修改；
        # 新业务必须显式传入自己的 Schema，避免误查候选人 Collection。
        self.collection_schema = collection_schema or build_candidate_collection_schema()

    async def retrieve(
        self,
        request: SearchRequest,
        *,
        mode: RetrievalMode | str,
    ) -> list[SearchHit]:
        """根据指定模式从 Milvus 召回实体。"""

        retrieval_mode = RetrievalMode(mode)

        if retrieval_mode == RetrievalMode.DENSE:
            vector = await self._embed_query(request.query)
            result = self.milvus_client.search(
                collection_name=self.collection_schema.collection_name,
                data=[vector],
                anns_field=self.collection_schema.dense_vector_field,
                search_params={"metric_type": "COSINE"},
                limit=request.dense_recall_k,
                filter=request.filter_expression,
                output_fields=list(request.output_fields),
            )
            return self._to_hits(result, source=RetrievalSource.DENSE)

        if retrieval_mode == RetrievalMode.SPARSE:
            # BM25 Function 在 Milvus 侧将 Schema 的 text_field 转为 sparse_vector；
            # 查询时直接传入原始文本，应用层不自行构造稀疏向量。
            result = self.milvus_client.search(
                collection_name=self.collection_schema.collection_name,
                data=[request.query],
                anns_field=self.collection_schema.sparse_vector_field,
                search_params={"metric_type": "BM25"},
                limit=request.sparse_recall_k,
                filter=request.filter_expression,
                output_fields=list(request.output_fields),
            )
            raw_hits = self._to_hits(result, source=RetrievalSource.SPARSE)
            # BM25 原始分数没有固定上限，不能直接当作前端百分比展示。
            # 仅在 sparse 模式内按本次结果池最高分归一化，保留原始分数供排障使用。
            return self._normalize_sparse_scores(raw_hits)

        vector = await self._embed_query(request.query)
        dense_request = AnnSearchRequest(
            data=[vector],
            anns_field=self.collection_schema.dense_vector_field,
            param={"metric_type": "COSINE"},
            limit=request.dense_recall_k,
            filter=request.filter_expression,
        )
        sparse_request = AnnSearchRequest(
            data=[request.query],
            anns_field=self.collection_schema.sparse_vector_field,
            param={"metric_type": "BM25"},
            limit=request.sparse_recall_k,
            filter=request.filter_expression,
        )
        result = self.milvus_client.hybrid_search(
            collection_name=self.collection_schema.collection_name,
            reqs=[dense_request, sparse_request],
            # RRF 不直接比较稠密相似度和 BM25 分数，适合两路异构召回融合。
            ranker=RRFRanker(k=request.rrf_k),
            limit=request.hybrid_limit,
            output_fields=list(request.output_fields),
        )
        return self._to_hits(result, source=RetrievalSource.HYBRID)

    async def _embed_query(self, query: str) -> list[float]:
        """生成并校验查询向量维度。"""

        vector = await self.embedding_service.embed_query(query)
        if len(vector) != self.collection_schema.vector_dim:
            raise ValueError(
                "Embedding维度不匹配："
                f"期望 {self.collection_schema.vector_dim}，实际 {len(vector)}"
            )
        return vector

    def _to_hits(
        self,
        search_result: list[list[dict[str, Any]]] | None,
        *,
        source: RetrievalSource,
    ) -> list[SearchHit]:
        """转换 Pymilvus 返回结构，并保留 Milvus 的排序。"""

        raw_hits = search_result[0] if search_result else []
        hits: list[SearchHit] = []

        for raw_hit in raw_hits:
            # MilvusClient 当前返回 entity；同时兼容部分版本直接平铺字段的格式。
            entity = raw_hit.get("entity") or raw_hit
            entity_id = (
                entity.get(self.collection_schema.primary_key_field)
                or raw_hit.get("id")
            )
            if not entity_id:
                raise ValueError(
                    "Milvus 命中结果缺少主键字段："
                    f"{self.collection_schema.primary_key_field}"
                )

            text = entity.get(self.collection_schema.text_field)
            metadata = {
                field_name: value
                for field_name, value in entity.items()
                if field_name
                not in {
                    self.collection_schema.primary_key_field,
                    self.collection_schema.text_field,
                }
            }
            hits.append(
                SearchHit(
                    entity_id=str(entity_id),
                    score=float(raw_hit.get("distance", raw_hit.get("score", 0.0))),
                    text=text,
                    metadata=metadata,
                    rank_source=source,
                )
            )

        return deduplicate_search_hits(hits)

    @staticmethod
    def _normalize_sparse_scores(hits: list[SearchHit]) -> list[SearchHit]:
        """将本次 BM25 结果池映射到 0 到 1 的相对匹配分。"""

        if not hits:
            return []

        max_score = max(hit.score for hit in hits)
        if max_score <= 0:
            return [
                replace(
                    hit,
                    score=0.0,
                    metadata={**hit.metadata, "raw_bm25_score": hit.score},
                )
                for hit in hits
            ]

        return [
            replace(
                hit,
                score=hit.score / max_score,
                metadata={**hit.metadata, "raw_bm25_score": hit.score},
            )
            for hit in hits
        ]
