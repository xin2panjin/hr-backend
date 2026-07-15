"""制度知识库检索接口的数据模型。"""

from typing import Literal

from pydantic import BaseModel, Field

from rag.retrieval_types import RetrievalMode


class KnowledgeSearchRequestSchema(BaseModel):
    """制度检索请求；知识库和 Milvus Collection 不由客户端指定。"""

    query: str = Field(..., min_length=1, description="制度问题或检索关键词")
    top_k: int = Field(5, ge=1, le=100, description="返回切片数量")
    retrieval_mode: RetrievalMode | None = Field(None, description="dense、sparse 或 hybrid")


class KnowledgeSearchHitSchema(BaseModel):
    """制度切片命中及其可用于来源展示的元数据。"""

    entity_id: str
    score: float
    text: str | None
    metadata: dict
    rank_source: str


class KnowledgeSearchResponseSchema(BaseModel):
    hits: list[KnowledgeSearchHitSchema]
    knowledge_base_key: str
    retrieval_mode: RetrievalMode
    trace_id: str
    elapsed_ms: float
    reranked: bool
    rerank_elapsed_ms: float
    artifact: "KnowledgeSourcesArtifactSchema"


class KnowledgeSourceSchema(BaseModel):
    """可定位到制度文档、章节和页码的来源引用。"""

    source_id: str
    document_id: str | None
    title: str | None
    version: str | None
    section_path: str | None
    page_number: int | None
    page_end: int | None
    score: float
    content: str | None
    chunk_ids: list[str]


class KnowledgeSourcesArtifactSchema(BaseModel):
    """HR 助手和未来其他 RAG 应用共享的来源 artifact。"""

    type: Literal["knowledge_sources"] = "knowledge_sources"
    title: str = "制度知识来源"
    knowledge_base_key: str
    trace_id: str
    sources: list[KnowledgeSourceSchema]
