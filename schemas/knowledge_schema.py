"""制度知识库管理接口的请求与响应模型。"""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class KnowledgeTextCleaningConfigSchema(BaseModel):
    """管理员可调整的文本清洗参数。"""

    normalize_whitespace: bool = True
    remove_urls_and_emails: bool = False
    remove_blockquote_metadata: bool = False


class KnowledgeChunkingConfigSchema(BaseModel):
    """管理员可调整的结构化切片参数。"""

    max_characters: int = Field(default=500, ge=50, le=2000)
    overlap_characters: int = Field(default=80, ge=0, le=1999)
    strategy: Literal[
        "structured_builtin",
        "fixed_length",
        "custom_character",
        "langchain_recursive",
        "custom_separator",
    ] = "structured_builtin"
    custom_separator: str = "。"
    recursive_separators: list[str] = Field(
        default_factory=lambda: [
            "\n\n", "\n", "。", "！", "？", "；", ";", "，", ",", " ", "",
        ]
    )
    custom_separators: list[str] | None = None

    @model_validator(mode="after")
    def validate_custom_separator_settings(self):
        """校验新的单分隔符策略，以及兼容旧任务的递归分隔符数组。"""

        if self.strategy == "custom_character":
            if not self.custom_separator:
                raise ValueError("custom_separator 不能为空")
            if len(self.custom_separator) > 20:
                raise ValueError("custom_separator 长度不能超过 20")
            return self
        if self.strategy == "langchain_recursive":
            if not 1 <= len(self.recursive_separators) <= 20:
                raise ValueError("recursive_separators 数量必须在 1 到 20 之间")
            for index, separator in enumerate(self.recursive_separators):
                if len(separator) > 20:
                    raise ValueError("recursive_separators 的单项长度不能超过 20")
                if not separator and index != len(self.recursive_separators) - 1:
                    raise ValueError("recursive_separators 的空字符串只能作为最后一个兜底分隔符")
            return self
        if self.strategy != "custom_separator":
            return self
        if self.custom_separators is None:
            raise ValueError("旧版 custom_separator 策略缺少 custom_separators")
        if not 1 <= len(self.custom_separators) <= 20:
            raise ValueError("custom_separators 数量必须在 1 到 20 之间")
        for index, separator in enumerate(self.custom_separators):
            if len(separator) > 20:
                raise ValueError("custom_separators 的单项长度不能超过 20")
            if not separator and index != len(self.custom_separators) - 1:
                raise ValueError("custom_separators 的空字符串只能作为最后一个兜底分隔符")
        return self


class KnowledgeTextProcessingConfigSchema(BaseModel):
    """预览和索引任务共用的完整文本处理配置。"""

    cleaning: KnowledgeTextCleaningConfigSchema = Field(
        default_factory=KnowledgeTextCleaningConfigSchema
    )
    chunking: KnowledgeChunkingConfigSchema = Field(
        default_factory=KnowledgeChunkingConfigSchema
    )


class KnowledgeRetrievalConfigSchema(BaseModel):
    """一个知识库可审计、可动态调整的检索策略。"""

    retrieval_mode: Literal["dense", "sparse", "hybrid"] = "hybrid"
    dense_recall_k: int = Field(default=20, ge=1, le=100)
    sparse_recall_k: int = Field(default=20, ge=1, le=100)
    hybrid_limit: int = Field(default=20, ge=1, le=100)
    rrf_k: int = Field(default=60, ge=1, le=1000)
    rerank_enabled: bool = False
    rerank_top_k: int = Field(default=5, ge=1, le=100)
    minimum_evidence_score: float = Field(default=0.3, ge=0, le=1)
    max_chunks_per_document: int = Field(default=2, ge=1, le=10)
    merge_adjacent_chunks: bool = True


class KnowledgePreviewChunkSchema(BaseModel):
    """一个可直接在管理页面展示的切片预览。"""

    chunk_index: int
    content: str
    character_count: int
    token_count: int
    section_path: str | None
    page_number: int | None


class KnowledgeDocumentPreviewSchema(BaseModel):
    """不落库的文本清洗与切片预览结果。"""

    raw_block_count: int
    cleaned_block_count: int
    chunk_count: int
    total_characters: int
    preview_truncated: bool
    processing_config: KnowledgeTextProcessingConfigSchema
    chunks: list[KnowledgePreviewChunkSchema]


class KnowledgeDocumentSchema(BaseModel):
    id: str
    title: str
    category: str | None
    file_name: str
    file_type: str
    version: str | None
    effective_date: date | None
    status: str
    visibility_scope: str
    indexed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class KnowledgeDocumentListSchema(BaseModel):
    items: list[KnowledgeDocumentSchema]
    total: int
    page: int
    size: int


class KnowledgeIndexTaskSchema(BaseModel):
    id: str
    document_id: str | None
    task_type: str
    status: str
    target_chunk_version: int | None
    retry_count: int
    last_error: str | None
    created_at: datetime
    completed_at: datetime | None


class KnowledgeIndexTaskListSchema(BaseModel):
    items: list[KnowledgeIndexTaskSchema]
    total: int
    page: int
    size: int


KnowledgeDocumentStatusQuery = Literal["draft", "active", "archived", "index_failed"]
