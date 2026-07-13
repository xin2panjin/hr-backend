"""RAG 检索层的通用数据契约。

本模块不依赖 Milvus、PostgreSQL 或具体模型，供 Retriever、Reranker
和 TalentSearchService 共同使用。
"""

from dataclasses import dataclass, field
from enum import StrEnum
from math import isfinite
from typing import Any, Iterable, Mapping


class RetrievalSource(StrEnum):
    """候选人命中结果的主要来源。"""

    DENSE = "dense"
    SPARSE = "sparse"
    HYBRID = "hybrid"


class RetrievalMode(StrEnum):
    """一次检索选择的 Milvus 召回模式。"""

    DENSE = "dense"
    SPARSE = "sparse"
    HYBRID = "hybrid"


@dataclass(frozen=True, slots=True)
class RetrievalRequest:
    """一次检索所需的通用输入。

    filter_expression 由业务服务根据当前用户权限构造，检索层只负责透传，
    不在 RAG 模块内自行决定数据权限。
    """

    query: str
    filter_expression: str = ""
    dense_recall_k: int = 30
    sparse_recall_k: int = 30
    hybrid_limit: int = 30
    output_fields: tuple[str, ...] = (
        "candidate_id",
        "profile_text",
        "position_id",
        "department_id",
        "creator_id",
        "status",
        "profile_version",
    )

    def __post_init__(self) -> None:
        normalized_query = self.query.strip()
        if not normalized_query:
            raise ValueError("检索问题不能为空")

        if min(
            self.dense_recall_k,
            self.sparse_recall_k,
            self.hybrid_limit,
        ) < 1:
            raise ValueError("检索数量必须大于 0")

        object.__setattr__(self, "query", normalized_query)


@dataclass(frozen=True, slots=True)
class RetrievalHit:
    """Retriever 返回的统一候选人命中结果。"""

    candidate_id: str
    score: float
    profile_text: str | None
    metadata: Mapping[str, Any] = field(default_factory=dict)
    rank_source: RetrievalSource = RetrievalSource.HYBRID

    def __post_init__(self) -> None:
        normalized_candidate_id = self.candidate_id.strip()
        if not normalized_candidate_id:
            raise ValueError("candidate_id 不能为空")

        if not isfinite(self.score):
            raise ValueError("检索分数必须是有限数值")

        object.__setattr__(self, "candidate_id", normalized_candidate_id)
        object.__setattr__(self, "metadata", dict(self.metadata))
        object.__setattr__(
            self,
            "rank_source",
            RetrievalSource(self.rank_source),
        )

    def to_dict(self) -> dict[str, Any]:
        """转换为便于日志记录和接口组装的普通字典。"""

        return {
            "candidate_id": self.candidate_id,
            "score": self.score,
            "profile_text": self.profile_text,
            "metadata": dict(self.metadata),
            "rank_source": self.rank_source.value,
        }


def deduplicate_hits(hits: Iterable[RetrievalHit]) -> list[RetrievalHit]:
    """按既有排序去重，同一候选人只保留首次出现的最高优先级结果。"""

    unique_hits: list[RetrievalHit] = []
    seen_candidate_ids: set[str] = set()

    for hit in hits:
        if hit.candidate_id in seen_candidate_ids:
            continue

        seen_candidate_ids.add(hit.candidate_id)
        unique_hits.append(hit)

    return unique_hits
