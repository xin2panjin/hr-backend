"""知识库检索结果的来源引用协议。"""

from dataclasses import dataclass
from typing import Any

from rag.retrieval_types import SearchHit


@dataclass(frozen=True, slots=True)
class KnowledgeSource:
    """一个可展示、可追溯的知识库证据来源。"""

    source_id: str
    document_id: str | None
    title: str | None
    version: str | None
    section_path: str | None
    page_number: int | None
    page_end: int | None
    score: float
    content: str | None
    chunk_ids: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        """转换为 API、Tool 和 SSE 均可复用的普通字典。"""

        return {
            "source_id": self.source_id,
            "document_id": self.document_id,
            "title": self.title,
            "version": self.version,
            "section_path": self.section_path,
            "page_number": self.page_number,
            "page_end": self.page_end,
            "score": self.score,
            "content": self.content,
            "chunk_ids": list(self.chunk_ids),
        }


def build_knowledge_sources(hits: list[SearchHit]) -> list[KnowledgeSource]:
    """将最终排序后的通用命中转换为稳定的来源列表。"""

    sources: list[KnowledgeSource] = []
    for hit in hits:
        metadata = dict(hit.metadata)
        chunk_ids = metadata.get("merged_chunk_ids") or [hit.entity_id]
        if not isinstance(chunk_ids, (list, tuple)):
            chunk_ids = [hit.entity_id]
        sources.append(
            KnowledgeSource(
                source_id=hit.entity_id,
                document_id=_text_value(metadata.get("document_id")),
                title=_text_value(metadata.get("title")),
                version=_text_value(metadata.get("version")),
                section_path=_text_value(metadata.get("section_path")),
                page_number=_int_value(metadata.get("page_number")),
                page_end=_int_value(metadata.get("page_end"))
                or _int_value(metadata.get("page_number")),
                score=hit.score,
                content=hit.text,
                chunk_ids=tuple(str(item) for item in chunk_ids),
            )
        )
    return sources


def _text_value(value: object) -> str | None:
    if value is None or not str(value).strip():
        return None
    return str(value)


def _int_value(value: object) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None
