"""知识库文本处理预览服务。

预览只使用系统临时目录，在响应前删除上传文件；不会写入业务数据库、
文件存储、Milvus，也不会调用 Embedding 服务。
"""

import asyncio
import tempfile
from dataclasses import dataclass
from pathlib import Path

from services.knowledge_document_service import AsyncReadableFile, KnowledgeDocumentService
from services.knowledge_text_extractor import KnowledgeTextExtractor
from services.knowledge_text_processing import (
    KnowledgeTextCleaner,
    KnowledgeTextProcessingConfig,
    StructuredKnowledgeChunker,
)


@dataclass(frozen=True, slots=True)
class KnowledgePreviewResult:
    """预览页面所需的统计数据和有限数量的切片。"""

    raw_block_count: int
    cleaned_block_count: int
    chunk_count: int
    total_characters: int
    preview_truncated: bool
    processing_config: KnowledgeTextProcessingConfig
    chunks: list


class KnowledgePreviewService:
    """执行“提取 → 清洗 → 切片”的无副作用预览。"""

    MAX_PREVIEW_CHUNKS = 100

    def __init__(
        self,
        *,
        text_extractor: KnowledgeTextExtractor | None = None,
        text_cleaner: KnowledgeTextCleaner | None = None,
        max_file_size_mb: int = 20,
    ):
        if max_file_size_mb < 1:
            raise ValueError("max_file_size_mb 必须大于 0")
        self.text_extractor = text_extractor or KnowledgeTextExtractor()
        self.text_cleaner = text_cleaner or KnowledgeTextCleaner()
        self.max_file_size_bytes = max_file_size_mb * 1024 * 1024

    async def preview(
        self,
        *,
        source: AsyncReadableFile,
        document_title: str,
        processing_config: KnowledgeTextProcessingConfig,
    ) -> KnowledgePreviewResult:
        """读取有限大小的临时文件，返回完整统计和有限数量的预览切片。"""

        file_name, file_extension = KnowledgeDocumentService.validate_source_file(source)
        normalized_title = KnowledgeDocumentService.normalize_required_text(
            document_title,
            "文档标题",
            max_length=200,
        )
        content = await source.read(self.max_file_size_bytes + 1)
        if not content:
            raise ValueError("不能上传空文件")
        if len(content) > self.max_file_size_bytes:
            raise ValueError(
                f"文件大小不能超过 {self.max_file_size_bytes // 1024 // 1024} MB"
            )

        with tempfile.TemporaryDirectory(prefix="knowledge-preview-") as temporary_directory:
            temporary_path = Path(temporary_directory) / f"source{file_extension}"
            await asyncio.to_thread(temporary_path.write_bytes, content)
            text_blocks = await asyncio.to_thread(
                self.text_extractor.extract,
                file_path=temporary_path,
                file_type=file_extension,
            )

        cleaned_text_blocks = self.text_cleaner.clean(
            text_blocks,
            config=processing_config.cleaning,
        )
        chunks = StructuredKnowledgeChunker.from_config(processing_config).chunk(
            document_title=normalized_title,
            text_blocks=cleaned_text_blocks,
        )
        return KnowledgePreviewResult(
            raw_block_count=len(text_blocks),
            cleaned_block_count=len(cleaned_text_blocks),
            chunk_count=len(chunks),
            total_characters=sum(len(chunk.content) for chunk in chunks),
            preview_truncated=len(chunks) > self.MAX_PREVIEW_CHUNKS,
            processing_config=processing_config,
            chunks=chunks[: self.MAX_PREVIEW_CHUNKS],
        )
