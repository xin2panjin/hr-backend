"""Milvus 稠密、BM25 稀疏与混合检索实现。"""

from dataclasses import replace
from typing import Any

from pymilvus import AnnSearchRequest, RRFRanker

from rag.embeddings import EmbeddingService
from rag.milvus_client import get_milvus_client
from rag.retrieval_types import (
    RetrievalHit,
    RetrievalMode,
    RetrievalRequest,
    RetrievalSource,
    deduplicate_hits,
)
from settings import settings


class MilvusHybridRetriever:
    """将 Milvus 的多种召回方式转换为统一的 ``RetrievalHit``。

    本类只处理向量检索请求和命中结果转换；权限过滤表达式由调用方传入，
    PostgreSQL 权限复核和候选人详情补全仍由业务 Service 负责。
    """

    def __init__(
        self,
        *,
        embedding_service: EmbeddingService | None = None,
        milvus_client=None,
    ):
        self.embedding_service = embedding_service or EmbeddingService()
        self.milvus_client = milvus_client or get_milvus_client()

    async def retrieve(
        self,
        request: RetrievalRequest,
        *,
        mode: RetrievalMode | str,
    ) -> list[RetrievalHit]:
        """根据指定模式从 Milvus 召回候选人。"""

        retrieval_mode = RetrievalMode(mode)

        if retrieval_mode == RetrievalMode.DENSE:
            vector = await self._embed_query(request.query)
            result = self.milvus_client.search(
                collection_name=settings.MILVUS_CANDIDATE_COLLECTION,
                data=[vector],
                anns_field="dense_vector",
                search_params={"metric_type": "COSINE"},
                limit=request.dense_recall_k,
                filter=request.filter_expression,
                output_fields=list(request.output_fields),
            )
            return self._to_hits(result, source=RetrievalSource.DENSE)

        if retrieval_mode == RetrievalMode.SPARSE:
            # BM25 Function 在 Milvus 侧将 profile_text 转为 sparse_vector；
            # 查询时直接传入原始文本，应用层不自行构造稀疏向量。
            result = self.milvus_client.search(
                collection_name=settings.MILVUS_CANDIDATE_COLLECTION,
                data=[request.query],
                anns_field="sparse_vector",
                search_params={"metric_type": "BM25"},
                limit=request.sparse_recall_k,
                filter=request.filter_expression,
                output_fields=list(request.output_fields),
            )
            raw_hits = self._to_hits(result, source=RetrievalSource.SPARSE)
            # BM25 原始分数没有固定上限，不能直接当作前端百分比展示。
            # 仅在 sparse 模式内按本次候选池最高分归一化，保留原始分数供排障使用。
            return self._normalize_sparse_scores(raw_hits)

        vector = await self._embed_query(request.query)
        dense_request = AnnSearchRequest(
            data=[vector],
            anns_field="dense_vector",
            param={"metric_type": "COSINE"},
            limit=request.dense_recall_k,
            filter=request.filter_expression,
        )
        sparse_request = AnnSearchRequest(
            data=[request.query],
            anns_field="sparse_vector",
            param={"metric_type": "BM25"},
            limit=request.sparse_recall_k,
            filter=request.filter_expression,
        )
        result = self.milvus_client.hybrid_search(
            collection_name=settings.MILVUS_CANDIDATE_COLLECTION,
            reqs=[dense_request, sparse_request],
            # RRF 不直接比较稠密相似度和 BM25 分数，适合两路异构召回融合。
            ranker=RRFRanker(),
            limit=request.hybrid_limit,
            output_fields=list(request.output_fields),
        )
        return self._to_hits(result, source=RetrievalSource.HYBRID)

    async def _embed_query(self, query: str) -> list[float]:
        """生成并校验查询向量维度。"""

        vector = await self.embedding_service.embed_query(query)
        if len(vector) != settings.MILVUS_CANDIDATE_VECTOR_DIM:
            raise ValueError(
                "Embedding维度不匹配："
                f"期望 {settings.MILVUS_CANDIDATE_VECTOR_DIM}，实际 {len(vector)}"
            )
        return vector

    def _to_hits(
        self,
        search_result: list[list[dict[str, Any]]] | None,
        *,
        source: RetrievalSource,
    ) -> list[RetrievalHit]:
        """转换 Pymilvus 返回结构，并保留 Milvus 的排序。"""

        raw_hits = search_result[0] if search_result else []
        hits: list[RetrievalHit] = []

        for raw_hit in raw_hits:
            # MilvusClient 当前返回 entity；同时兼容部分版本直接平铺字段的格式。
            entity = raw_hit.get("entity") or raw_hit
            candidate_id = entity.get("candidate_id") or raw_hit.get("id")
            if not candidate_id:
                raise ValueError("Milvus 命中结果缺少 candidate_id")

            profile_text = entity.get("profile_text")
            metadata = {
                field_name: value
                for field_name, value in entity.items()
                if field_name not in {"candidate_id", "profile_text"}
            }
            hits.append(
                RetrievalHit(
                    candidate_id=str(candidate_id),
                    score=float(raw_hit.get("distance", raw_hit.get("score", 0.0))),
                    profile_text=profile_text,
                    metadata=metadata,
                    rank_source=source,
                )
            )

        return deduplicate_hits(hits)

    @staticmethod
    def _normalize_sparse_scores(hits: list[RetrievalHit]) -> list[RetrievalHit]:
        """将本次 BM25 候选池映射到 0 到 1 的相对匹配分。"""

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
