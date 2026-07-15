"""通用知识库检索应用服务。"""

from dataclasses import dataclass, replace
from time import perf_counter
from uuid import uuid4

from loguru import logger

from rag.knowledge_base_definitions import KnowledgeBaseDefinition
from rag.knowledge_sources import KnowledgeSource, build_knowledge_sources
from rag.rerankers import Reranker, build_reranker
from rag.retrieval_types import RetrievalMode, SearchHit, SearchRequest
from rag.retrievers.milvus_hybrid_retriever import (
    MilvusCollectionSchema,
    MilvusHybridRetriever,
)


@dataclass(frozen=True, slots=True)
class KnowledgeSearchResult:
    """一次知识库召回的内部结果，保留查询模式和耗时便于观测。"""

    hits: list[SearchHit]
    knowledge_base_key: str
    retrieval_mode: RetrievalMode
    trace_id: str
    elapsed_ms: float
    reranked: bool
    rerank_elapsed_ms: float
    sources: list[KnowledgeSource]


class KnowledgeSearchService:
    """根据受控知识库定义执行 Dense、Sparse 或 Hybrid 召回。

    服务只负责把知识库定义转换为通用 Retriever 配置，并构造可见范围过滤；
    PostgreSQL 文档详情补全、Reranker 和来源聚合由后续应用层继续处理。
    """

    def __init__(
        self,
        *,
        knowledge_base_definition: KnowledgeBaseDefinition,
        retriever: MilvusHybridRetriever | None = None,
        embedding_service=None,
        milvus_client=None,
        reranker: Reranker | None = None,
    ):
        self.definition = knowledge_base_definition
        self.retriever = retriever or MilvusHybridRetriever(
            embedding_service=embedding_service,
            milvus_client=milvus_client,
            collection_schema=self._build_retriever_schema(),
        )
        # Reranker 不在构造阶段访问网络；只有知识库配置开启时才会实际调用。
        self.reranker = reranker or build_reranker()

    async def search(
        self,
        *,
        query: str,
        retrieval_mode: RetrievalMode | str | None = None,
        top_k: int | None = None,
        visibility_scope: str = "hr_only",
        filter_expression: str | None = None,
    ) -> KnowledgeSearchResult:
        """执行一次受控知识库召回。

        ``filter_expression`` 只允许在后端 Service 内传入；公开接口默认使用
        ``hr_only``，调用方不能通过请求参数指定任意 Collection 或过滤字段。
        """

        config = self.definition.retrieval_config
        mode = RetrievalMode(retrieval_mode or config.get("retrieval_mode", "hybrid"))
        configured_top_k = config.get("hybrid_limit", 20) if top_k is None else top_k
        normalized_top_k = int(configured_top_k)
        if not 1 <= normalized_top_k <= 100:
            raise ValueError("top_k 必须在 1 到 100 之间")

        if filter_expression is None:
            normalized_scope = visibility_scope.strip()
            if not normalized_scope:
                raise ValueError("visibility_scope 不能为空")
            escaped_scope = normalized_scope.replace('\\', '\\\\').replace('"', '\\"')
            filter_expression = f'visibility_scope == "{escaped_scope}"'

        request = SearchRequest(
            query=query,
            filter_expression=filter_expression,
            dense_recall_k=int(config.get("dense_recall_k", normalized_top_k)),
            sparse_recall_k=int(config.get("sparse_recall_k", normalized_top_k)),
            hybrid_limit=max(int(config.get("hybrid_limit", normalized_top_k)), normalized_top_k),
            rrf_k=int(config.get("rrf_k", 60)),
            output_fields=self._output_fields(),
        )
        trace_id = uuid4().hex
        started_at = perf_counter()
        logger.info(
            "知识库检索开始 trace_id={} knowledge_base={} mode={} query_length={} filter_fields={}",
            trace_id,
            self.definition.key,
            mode.value,
            len(request.query),
            self._filter_fields(filter_expression),
        )
        hits = await self.retriever.retrieve(request, mode=mode)
        hits = hits[: max(normalized_top_k, int(config.get("rerank_top_k", normalized_top_k)))]
        rerank_enabled = bool(config.get("rerank_enabled", False))
        reranked = False
        rerank_elapsed_ms = 0.0
        if rerank_enabled and hits:
            rerank_started_at = perf_counter()
            try:
                reranked_hits = await self.reranker.rerank(
                    query=request.query,
                    hits=hits,
                    trace_id=trace_id,
                )
                minimum_score = float(config.get("minimum_evidence_score", 0.0))
                hits = [hit for hit in reranked_hits if hit.score >= minimum_score]
                reranked = True
                logger.info(
                    "知识库 Rerank 完成 trace_id={} knowledge_base={} input_count={} output_count={} minimum_score={}",
                    trace_id,
                    self.definition.key,
                    len(reranked_hits),
                    len(hits),
                    minimum_score,
                )
            except Exception as exc:
                # 外部模型失败时保留 Milvus 排序，确保制度检索仍可用。
                logger.warning(
                    "知识库 Rerank 降级 trace_id={} knowledge_base={} error_type={}",
                    trace_id,
                    self.definition.key,
                    type(exc).__name__,
                )
            rerank_elapsed_ms = (perf_counter() - rerank_started_at) * 1000
        hits = self._organize_hits(
            hits,
            top_k=normalized_top_k,
            max_chunks_per_document=int(config.get("max_chunks_per_document", 2)),
            merge_adjacent_chunks=bool(config.get("merge_adjacent_chunks", True)),
        )
        sources = build_knowledge_sources(hits)
        elapsed_ms = (perf_counter() - started_at) * 1000
        logger.info(
            "知识库检索完成 trace_id={} knowledge_base={} mode={} hit_count={} reranked={} score_min={} score_max={} elapsed_ms={:.2f}",
            trace_id,
            self.definition.key,
            mode.value,
            len(hits),
            reranked,
            f"{min((hit.score for hit in hits), default=0.0):.4f}",
            f"{max((hit.score for hit in hits), default=0.0):.4f}",
            elapsed_ms,
        )
        return KnowledgeSearchResult(
            hits=hits,
            knowledge_base_key=self.definition.key,
            retrieval_mode=mode,
            trace_id=trace_id,
            elapsed_ms=elapsed_ms,
            reranked=reranked,
            rerank_elapsed_ms=rerank_elapsed_ms,
            sources=sources,
        )

    def _build_retriever_schema(self) -> MilvusCollectionSchema:
        """将知识库定义转换为通用 Retriever 的字段映射。"""

        collection = self.definition.collection_definition
        return MilvusCollectionSchema(
            collection_name=collection.collection_name,
            primary_key_field=collection.primary_key_field,
            text_field=collection.text_field,
            vector_dim=collection.vector_dim,
            dense_vector_field=collection.dense_vector_field,
            sparse_vector_field=collection.sparse_vector_field,
        )

    @classmethod
    def _organize_hits(
        cls,
        hits: list[SearchHit],
        *,
        top_k: int,
        max_chunks_per_document: int,
        merge_adjacent_chunks: bool,
    ) -> list[SearchHit]:
        """按实体去重、合并相邻切片并限制单文档占比。"""

        if max_chunks_per_document < 1:
            raise ValueError("max_chunks_per_document 必须大于 0")

        unique_hits: list[SearchHit] = []
        seen_entity_ids: set[str] = set()
        for hit in hits:
            if hit.entity_id in seen_entity_ids:
                continue
            seen_entity_ids.add(hit.entity_id)
            unique_hits.append(hit)

        if merge_adjacent_chunks:
            unique_hits = cls._merge_adjacent_hits(unique_hits)

        # 同一文档的非相邻切片仍可能重复占据结果，限制其最大保留数量。
        organized: list[SearchHit] = []
        document_counts: dict[str, int] = {}
        for hit in unique_hits:
            document_id = cls._metadata_text(hit, "document_id")
            if document_id:
                current_count = document_counts.get(document_id, 0)
                if current_count >= max_chunks_per_document:
                    continue
                document_counts[document_id] = current_count + 1
            organized.append(hit)
            if len(organized) >= top_k:
                break
        return organized

    @classmethod
    def _merge_adjacent_hits(cls, hits: list[SearchHit]) -> list[SearchHit]:
        """仅合并同文档、同版本、同章节且 chunk_index 连续的命中。"""

        mergeable: dict[tuple[str, str, str], list[SearchHit]] = {}
        unmergeable: list[SearchHit] = []
        for hit in hits:
            document_id = cls._metadata_text(hit, "document_id")
            chunk_index = cls._metadata_int(hit, "chunk_index")
            if not document_id or chunk_index is None:
                unmergeable.append(hit)
                continue
            key = (
                document_id,
                cls._metadata_text(hit, "chunk_version") or "1",
                cls._metadata_text(hit, "section_path") or "",
            )
            mergeable.setdefault(key, []).append(hit)

        merged_hits = list(unmergeable)
        for grouped_hits in mergeable.values():
            grouped_hits.sort(key=lambda hit: cls._metadata_int(hit, "chunk_index") or 0)
            current = grouped_hits[0]
            for next_hit in grouped_hits[1:]:
                current_index = cls._metadata_int(current, "chunk_index")
                next_index = cls._metadata_int(next_hit, "chunk_index")
                if current_index is not None and next_index == current_index + 1:
                    current = cls._merge_two_hits(current, next_hit)
                else:
                    merged_hits.append(current)
                    current = next_hit
            merged_hits.append(current)

        # 合并后以组内最高分作为排序分，保持与 Reranker 的结果契约一致。
        return sorted(merged_hits, key=lambda hit: hit.score, reverse=True)

    @classmethod
    def _merge_two_hits(cls, left: SearchHit, right: SearchHit) -> SearchHit:
        """合并两个相邻切片，并保留可追溯的原始切片 ID。"""

        left_metadata = dict(left.metadata)
        right_metadata = dict(right.metadata)
        left_ids = left_metadata.get("merged_chunk_ids", [left.entity_id])
        right_ids = right_metadata.get("merged_chunk_ids", [right.entity_id])
        merged_ids = [*left_ids, *right_ids]
        page_numbers = [
            page
            for page in (
                cls._metadata_int(left, "page_number"),
                cls._metadata_int(right, "page_number"),
                left_metadata.get("page_end"),
                right_metadata.get("page_end"),
            )
            if page is not None
        ]
        metadata = {
            **left_metadata,
            "merged_chunk_ids": merged_ids,
            "merged_chunk_count": len(merged_ids),
        }
        if page_numbers:
            metadata["page_number"] = min(page_numbers)
            metadata["page_end"] = max(page_numbers)
        return replace(
            left,
            score=max(left.score, right.score),
            text=cls._join_text(left.text, right.text),
            metadata=metadata,
        )

    @staticmethod
    def _join_text(left: str | None, right: str | None) -> str | None:
        """拼接正文并去掉切片重叠造成的重复前缀。"""

        if not left:
            return right
        if not right:
            return left
        max_overlap = min(len(left), len(right), 200)
        for overlap in range(max_overlap, 0, -1):
            if left[-overlap:] == right[:overlap]:
                return left + right[overlap:]
        return f"{left}\n{right}"

    @staticmethod
    def _metadata_text(hit: SearchHit, key: str) -> str | None:
        value = hit.metadata.get(key)
        return str(value) if value is not None and str(value).strip() else None

    @staticmethod
    def _metadata_int(hit: SearchHit, key: str) -> int | None:
        value = hit.metadata.get(key)
        try:
            return int(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    def _output_fields(self) -> tuple[str, ...]:
        """返回制度切片需要展示和构造来源的字段集合。"""

        collection = self.definition.collection_definition
        # ``SearchHit.text`` 由 Retriever 从 ``text_field`` 读取。遗漏该字段时，
        # 检索仍会命中标题和章节等元数据，但无法把正文交给模型和证据卡片。
        field_names = [
            collection.text_field,
            *(
                field.field_name
                for field in collection.metadata_fields
                if field.field_name not in {"visibility_scope"}
            ),
            "visibility_scope",
        ]
        return tuple(dict.fromkeys(field_names))

    @staticmethod
    def _filter_fields(filter_expression: str) -> list[str]:
        """日志只记录过滤字段名，不记录具体值。"""

        known_fields = ("visibility_scope", "knowledge_base_id", "document_id")
        return [field for field in known_fields if field in filter_expression]
