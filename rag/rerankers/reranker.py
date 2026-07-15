"""可复用的专用 Rerank 实现。"""

from abc import ABC, abstractmethod
from dataclasses import replace
from time import perf_counter
from typing import Any, Protocol
from urllib.parse import urlsplit

import httpx
from loguru import logger

from rag.retrieval_types import SearchHit
from settings import settings


class Reranker(Protocol):
    """对已召回的通用实体命中结果进行二次排序。"""

    async def rerank(
        self,
        *,
        query: str,
        hits: list[SearchHit],
        trace_id: str | None = None,
    ) -> list[SearchHit]:
        """根据查询和命中文本，返回新的命中排序。"""


class RerankAPIError(RuntimeError):
    """专用 Rerank API 调用或响应解析失败时抛出。"""


class NoopReranker:
    """关闭重排时使用，不访问模型或外部服务。"""

    async def rerank(
        self,
        *,
        query: str,
        hits: list[SearchHit],
        trace_id: str | None = None,
    ) -> list[SearchHit]:
        """返回输入顺序的副本，保持调用链可替换。"""

        return list(hits)


class APIReranker(ABC):
    """封装专用 Rerank API 共有的鉴权、请求和结果映射逻辑。"""

    def __init__(
        self,
        *,
        model: str | None = None,
        base_url: str | None = None,
        api_key: str | None = None,
        timeout_seconds: float | None = None,
        max_text_chars: int | None = None,
        max_profile_chars: int | None = None,
        client: httpx.AsyncClient | None = None,
    ):
        self.model = model or settings.TALENT_SEARCH_RERANK_MODEL or "qwen3-rerank"
        self.base_url = base_url or settings.TALENT_SEARCH_RERANK_BASE_URL
        self.api_key = (
            api_key
            or settings.TALENT_SEARCH_RERANK_API_KEY
            or settings.DASHSCOPE_API_KEY
        )
        self.timeout_seconds = (
            timeout_seconds or settings.TALENT_SEARCH_RERANK_TIMEOUT_SECONDS
        )
        # max_profile_chars 是旧构造参数，保留它以兼容既有调用方；新业务
        # 使用 max_text_chars，避免把候选人画像概念带入通用 RAG 内核。
        self.max_text_chars = (
            max_text_chars
            or max_profile_chars
            or settings.TALENT_SEARCH_RERANK_MAX_PROFILE_CHARS
        )
        self._client = client

    async def rerank(
        self,
        *,
        query: str,
        hits: list[SearchHit],
        trace_id: str | None = None,
    ) -> list[SearchHit]:
        """调用专用模型，并将 API 相关性分数映射回通用命中结果。"""

        if len(hits) <= 1:
            logger.info(
                "Rerank 跳过 trace_id={} protocol={} model={} hit_count={} reason=insufficient_hits",
                trace_id or "-",
                self.protocol_name,
                self.model,
                len(hits),
            )
            return list(hits)
        if not self.base_url:
            raise RerankAPIError("未配置 TALENT_SEARCH_RERANK_BASE_URL")

        started_at = perf_counter()
        documents = [
            (hit.text or "")[: self.max_text_chars] for hit in hits
        ]
        logger.info(
            "Rerank 开始 trace_id={} protocol={} model={} api_host={} hit_count={} max_text_chars={}",
            trace_id or "-",
            self.protocol_name,
            self.model,
            self._api_host,
            len(hits),
            self.max_text_chars,
        )
        try:
            body = await self._post(
                self._build_payload(query=query, documents=documents, top_n=len(documents))
            )
            api_results = self._extract_results(body)
            reranked_hits = self._apply_results(api_results, hits)
        except Exception as exc:
            logger.warning(
                "Rerank 失败 trace_id={} protocol={} model={} api_host={} "
                "hit_count={} error_type={} elapsed_ms={:.2f}",
                trace_id or "-",
                self.protocol_name,
                self.model,
                self._api_host,
                len(hits),
                type(exc).__name__,
                (perf_counter() - started_at) * 1000,
            )
            raise

        scores = [hit.score for hit in reranked_hits]
        logger.info(
            "Rerank 完成 trace_id={} protocol={} model={} api_result_count={} "
            "output_count={} score_min={:.4f} score_max={:.4f} elapsed_ms={:.2f}",
            trace_id or "-",
            self.protocol_name,
            self.model,
            len(api_results),
            len(reranked_hits),
            min(scores),
            max(scores),
            (perf_counter() - started_at) * 1000,
        )
        return reranked_hits

    @property
    def protocol_name(self) -> str:
        """记录协议名，避免日志把实现类名作为对外配置。"""

        return "api"

    @property
    def _api_host(self) -> str:
        """仅记录 API 主机，不记录可能包含敏感信息的完整 URL。"""

        return urlsplit(self.base_url or "").netloc or "unknown"

    @abstractmethod
    def _build_payload(
        self,
        *,
        query: str,
        documents: list[str],
        top_n: int,
    ) -> dict[str, Any]:
        """按具体协议构造请求体。"""

    @abstractmethod
    def _extract_results(self, body: dict[str, Any]) -> list[dict[str, Any]]:
        """按具体协议提取结果数组。"""

    async def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        """发送认证请求；Base URL 是完整的 Rerank API 地址。"""

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        if self._client is not None:
            response = await self._client.post(
                self.base_url,
                json=payload,
                headers=headers,
                timeout=self.timeout_seconds,
            )
        else:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                response = await client.post(
                    self.base_url,
                    json=payload,
                    headers=headers,
                )

        response.raise_for_status()
        body = response.json()
        if not isinstance(body, dict):
            raise RerankAPIError("Rerank API 响应不是 JSON 对象")
        return body

    @staticmethod
    def _apply_results(
        results: list[dict[str, Any]],
        hits: list[SearchHit],
    ) -> list[SearchHit]:
        """校验 index 与 0 到 1 的相关性分数，保留缺失项的原始顺序。"""

        scored_hits: list[tuple[SearchHit, float]] = []
        seen_indexes: set[int] = set()
        for item in results:
            try:
                index = int(item["index"])
                score = float(item["relevance_score"])
            except (KeyError, TypeError, ValueError):
                continue
            if index in seen_indexes or not 0 <= index < len(hits):
                continue
            if not 0 <= score <= 1:
                continue
            seen_indexes.add(index)
            scored_hits.append((hits[index], score))

        if not scored_hits:
            raise RerankAPIError("Rerank API 响应不含有效排序结果")

        scored_hits.sort(key=lambda item: item[1], reverse=True)
        reranked_hits = [replace(hit, score=score) for hit, score in scored_hits]
        reranked_hits.extend(
            hit for index, hit in enumerate(hits) if index not in seen_indexes
        )
        return reranked_hits


class CohereCompatibleReranker(APIReranker):
    """适配 ``query/documents/top_n -> results`` 的主流 Rerank 协议。

    可用于 Cohere、Jina、DashScope qwen3-rerank 和自建兼容服务。Base URL
    由配置直接提供完整请求地址，因此替换云平台通常只需要改 URL、Key 和模型名。
    """

    @property
    def protocol_name(self) -> str:
        return "cohere_compatible"

    def _build_payload(
        self,
        *,
        query: str,
        documents: list[str],
        top_n: int,
    ) -> dict[str, Any]:
        return {
            "model": self.model,
            "query": query,
            "documents": documents,
            "top_n": top_n,
        }

    def _extract_results(self, body: dict[str, Any]) -> list[dict[str, Any]]:
        results = body.get("results")
        if not isinstance(results, list):
            raise RerankAPIError("兼容 Rerank 响应缺少 results 数组")
        return [item for item in results if isinstance(item, dict)]


class DashScopeNativeReranker(APIReranker):
    """适配 ``input/parameters -> output.results`` 的 DashScope 原生协议。"""

    @property
    def protocol_name(self) -> str:
        return "dashscope_native"

    def _build_payload(
        self,
        *,
        query: str,
        documents: list[str],
        top_n: int,
    ) -> dict[str, Any]:
        return {
            "model": self.model,
            "input": {
                "query": query,
                "documents": documents,
            },
            "parameters": {
                "top_n": top_n,
                "return_documents": False,
            },
        }

    def _extract_results(self, body: dict[str, Any]) -> list[dict[str, Any]]:
        output = body.get("output")
        results = output.get("results") if isinstance(output, dict) else None
        if not isinstance(results, list):
            raise RerankAPIError(
                "DashScope 原生 Rerank 响应缺少 output.results 数组"
            )
        return [item for item in results if isinstance(item, dict)]


def build_reranker() -> Reranker:
    """按配置创建专用 Rerank 实例；关闭时不创建 HTTP 客户端。"""

    if not settings.TALENT_SEARCH_RERANK_ENABLED:
        return NoopReranker()
    if settings.TALENT_SEARCH_RERANK_PROVIDER == "cohere_compatible":
        return CohereCompatibleReranker()
    if settings.TALENT_SEARCH_RERANK_PROVIDER == "dashscope_native":
        return DashScopeNativeReranker()
    return NoopReranker()
