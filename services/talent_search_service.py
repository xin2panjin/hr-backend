import hashlib
from time import perf_counter
from uuid import uuid4

from loguru import logger

from models.candidate import CandidateStatusEnum
from models.user import UserModel
from rag.embeddings import EmbeddingService
from rag.rerankers import Reranker, build_reranker
from rag.retrieval_types import (
    RetrievalMode,
    RetrievalRequest,
    deduplicate_hits,
)
from rag.retrievers.milvus_hybrid_retriever import MilvusHybridRetriever
from repository.candidate_repo import CandidateRepo
from settings import settings
from iam.policies.candidate_policy import CandidatePolicy


class TalentSearchService:
    """人才库语义检索服务。

    第一阶段只做检索服务，不接 Agent。
    """

    def __init__(
        self,
        candidate_repo: CandidateRepo,
        embedding_service: EmbeddingService | None = None,
        milvus_client=None,
        retriever: MilvusHybridRetriever | None = None,
        reranker: Reranker | None = None,
        candidate_policy: type[CandidatePolicy] = CandidatePolicy,
    ):
        self.candidate_repo = candidate_repo
        # 保留 embedding_service、milvus_client 参数，兼容现有调用方和测试注入；
        # 新代码优先直接注入 retriever，便于替换或独立测试检索层。
        self.retriever = retriever or MilvusHybridRetriever(
            embedding_service=embedding_service,
            milvus_client=milvus_client,
        )
        self.reranker = reranker or build_reranker()
        self.candidate_policy = candidate_policy

    async def search(
        self,
        *,
        query: str,
        current_user: UserModel,
        top_k: int = 10,
        position_id: str | None = None,
        status: CandidateStatusEnum | None = None,
        retrieval_mode: RetrievalMode | str | None = None,
    ) -> list[dict]:
        """根据自然语言检索候选人，并完成权限复核与详情补全。"""

        if top_k < 1:
            raise ValueError("top_k 必须大于 0")

        trace_id = uuid4().hex
        started_at = perf_counter()
        retrieval_mode = RetrievalMode(
            retrieval_mode or settings.TALENT_SEARCH_RETRIEVAL_MODE
        )
        milvus_filter = self._build_milvus_filter(
            current_user=current_user,
            position_id=position_id,
            status=status,
        )
        logger.info(
            "人才库检索开始 trace_id={} mode={} query_fingerprint={} query_length={} filter_fields={}",
            trace_id,
            retrieval_mode.value,
            self._query_fingerprint(query),
            len(query.strip()),
            self._summarize_filter_fields(milvus_filter),
        )

        request = RetrievalRequest(
            query=query,
            filter_expression=milvus_filter,
            dense_recall_k=settings.TALENT_SEARCH_DENSE_RECALL_K,
            sparse_recall_k=settings.TALENT_SEARCH_SPARSE_RECALL_K,
            hybrid_limit=settings.TALENT_SEARCH_HYBRID_LIMIT,
        )
        retrieved_hits = await self.retriever.retrieve(
            request,
            mode=retrieval_mode,
        )
        retrieval_elapsed_ms = (perf_counter() - started_at) * 1000

        hits = retrieved_hits
        rerank_elapsed_ms = 0.0
        if settings.TALENT_SEARCH_RERANK_ENABLED:
            rerank_started_at = perf_counter()
            try:
                hits = await self.reranker.rerank(
                    query=request.query,
                    hits=hits,
                    trace_id=trace_id,
                )
            except Exception as exc:
                # 模型超时或格式异常时保留 Milvus 原始排序，保证检索可用。
                logger.warning(
                    "人才库 Rerank 降级 trace_id={} provider={} error_type={}",
                    trace_id,
                    settings.TALENT_SEARCH_RERANK_PROVIDER,
                    type(exc).__name__,
                )
            rerank_elapsed_ms = (perf_counter() - rerank_started_at) * 1000

        # 即使后续接入的 Reranker 出现重复输出，也不能让同一候选人重复返回。
        hits = deduplicate_hits(hits)
        candidate_ids = [hit.candidate_id for hit in hits]
        score_map = {hit.candidate_id: hit.score for hit in hits}
        profile_text_map = {hit.candidate_id: hit.profile_text for hit in hits}

        # PostgreSQL 二次复核权限和最新候选人状态。
        candidates = await self.candidate_repo.list_visible_by_ids(
            candidate_ids=candidate_ids,
            current_user=current_user,
        )

        # Retriever 使用较大的候选池召回；经过 SQL 权限复核后才按对外 top_k 截断。
        results = [
            {
                "candidate_id": candidate.id,
                "name": candidate.name,
                "position_title": candidate.position.title if candidate.position else None,
                "status": candidate.status,
                "score": score_map.get(candidate.id, 0.0),
                "profile_text": profile_text_map.get(candidate.id),
            }
            for candidate in candidates
        ][:top_k]
        self._log_search_completed(
            trace_id=trace_id,
            mode=retrieval_mode,
            retrieved_hits=retrieved_hits,
            rerank_elapsed_ms=rerank_elapsed_ms,
            retrieval_elapsed_ms=retrieval_elapsed_ms,
            total_elapsed_ms=(perf_counter() - started_at) * 1000,
            final_candidate_ids=[item["candidate_id"] for item in results],
        )
        return results

    @staticmethod
    def _query_fingerprint(query: str) -> str:
        """生成可关联日志的查询指纹，不写入原始查询文本。"""

        return hashlib.sha256(query.strip().encode("utf-8")).hexdigest()[:12]

    @staticmethod
    def _summarize_filter_fields(filter_expression: str) -> list[str]:
        """只记录过滤字段名，不记录部门、用户等具体标量值。"""

        field_names = ("department_id", "position_id", "creator_id", "status")
        return [field_name for field_name in field_names if field_name in filter_expression]

    @staticmethod
    def _log_search_completed(
        *,
        trace_id: str,
        mode: RetrievalMode,
        retrieved_hits: list,
        rerank_elapsed_ms: float,
        retrieval_elapsed_ms: float,
        total_elapsed_ms: float,
        final_candidate_ids: list[str],
    ) -> None:
        """记录脱敏检索链路指标，不记录完整查询或候选人画像。"""

        dense_recall_count = len(retrieved_hits) if mode == RetrievalMode.DENSE else 0
        sparse_recall_count = len(retrieved_hits) if mode == RetrievalMode.SPARSE else 0
        fusion_result_count = len(retrieved_hits) if mode == RetrievalMode.HYBRID else 0

        logger.info(
            "人才库检索完成 trace_id={} mode={} dense_recall_count={} "
            "sparse_recall_count={} fusion_result_count={} "
            "dense_recall_limit={} sparse_recall_limit={} rerank_enabled={} "
            "rerank_elapsed_ms={:.2f} retrieval_elapsed_ms={:.2f} "
            "total_elapsed_ms={:.2f} final_count={} final_candidate_ids={}",
            trace_id,
            mode.value,
            dense_recall_count,
            sparse_recall_count,
            fusion_result_count,
            settings.TALENT_SEARCH_DENSE_RECALL_K,
            settings.TALENT_SEARCH_SPARSE_RECALL_K,
            settings.TALENT_SEARCH_RERANK_ENABLED,
            rerank_elapsed_ms,
            retrieval_elapsed_ms,
            total_elapsed_ms,
            len(final_candidate_ids),
            final_candidate_ids,
        )

    def _build_milvus_filter(
        self,
        *,
        current_user: UserModel,
        position_id: str | None,
        status: CandidateStatusEnum | None,
    ) -> str:
        """委托候选人策略构造 Milvus 标量过滤表达式。"""

        return self.candidate_policy.build_milvus_filter(
            actor=current_user,
            position_id=position_id,
            status=status,
        )
