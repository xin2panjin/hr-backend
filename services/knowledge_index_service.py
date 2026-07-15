"""知识库索引的通用切片与幂等任务能力。

本模块当前负责 A5 的纯切片和任务登记；A6 会在同一模块补充文本提取、
Embedding、Milvus 写入和任务状态流转，避免把一条索引链路拆散到多个 Service。
"""

import asyncio
import hashlib
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from models.knowledge import (
    KnowledgeBaseModel,
    KnowledgeDocumentModel,
    KnowledgeDocumentChunkModel,
    KnowledgeDocumentStatusEnum,
    KnowledgeIndexTaskModel,
    KnowledgeIndexTaskStatusEnum,
    KnowledgeIndexTaskTypeEnum,
)
from rag.embeddings import EmbeddingService
from rag.knowledge_base_definitions import KnowledgeBaseDefinition
from rag.milvus_client import get_milvus_client
from services.knowledge_text_extractor import KnowledgeTextExtractor
from services.knowledge_text_processing import (
    KnowledgeTextCleaner,
    KnowledgeTextProcessingConfig,
    StructuredKnowledgeChunker,
)
from settings import settings


@dataclass(frozen=True, slots=True)
class KnowledgeIndexTaskRegistrationResult:
    """幂等创建索引任务的结果。"""

    task: KnowledgeIndexTaskModel
    created: bool


@dataclass(frozen=True, slots=True)
class KnowledgeIndexExecutionResult:
    """一次索引任务执行后的可审计摘要。"""

    task_id: str
    succeeded: bool
    chunk_count: int = 0
    error_type: str | None = None


class KnowledgeIndexService:
    """知识库索引任务的登记与执行入口。"""

    def __init__(
        self,
        session: AsyncSession,
        *,
        knowledge_base_definition: KnowledgeBaseDefinition | None = None,
        embedding_service: EmbeddingService | None = None,
        milvus_client=None,
        text_extractor: KnowledgeTextExtractor | None = None,
        chunker: StructuredKnowledgeChunker | None = None,
        text_cleaner: KnowledgeTextCleaner | None = None,
        file_path_resolver=None,
    ):
        self.session = session
        # 任务登记不依赖定义；真正执行时必须显式绑定受控知识库定义，
        # 防止任意数据库记录把内容写入错误的 Milvus Collection。
        self.knowledge_base_definition = knowledge_base_definition
        # 仅登记任务时不应初始化外部客户端；延迟到真正执行任务时再创建。
        self.embedding_service = embedding_service
        self.milvus_client = milvus_client
        self.text_extractor = text_extractor or KnowledgeTextExtractor()
        self.chunker = chunker or StructuredKnowledgeChunker()
        self.text_cleaner = text_cleaner or KnowledgeTextCleaner()
        self.file_path_resolver = file_path_resolver or self._resolve_local_file_path

    async def ensure_upsert_task(
        self,
        *,
        document: KnowledgeDocumentModel,
        target_chunk_version: int = 1,
        processing_config: KnowledgeTextProcessingConfig | None = None,
    ) -> KnowledgeIndexTaskRegistrationResult:
        """确保同一文档内容版本只有一个 UPSERT 索引任务。"""

        return await self._ensure_task(
            document=document,
            task_type=KnowledgeIndexTaskTypeEnum.UPSERT,
            target_chunk_version=target_chunk_version,
            source="document_registration",
            processing_config=processing_config,
        )

    async def ensure_rebuild_task(
        self,
        *,
        document: KnowledgeDocumentModel,
        target_chunk_version: int,
        processing_config: KnowledgeTextProcessingConfig | None = None,
    ) -> KnowledgeIndexTaskRegistrationResult:
        """创建新的 REBUILD 任务，使用新的切片版本避免与旧任务混淆。"""

        return await self._ensure_task(
            document=document,
            task_type=KnowledgeIndexTaskTypeEnum.REBUILD,
            target_chunk_version=target_chunk_version,
            source="document_rebuild",
            processing_config=processing_config,
        )

    async def ensure_delete_task(
        self,
        *,
        document: KnowledgeDocumentModel,
    ) -> KnowledgeIndexTaskRegistrationResult:
        """创建删除向量与审计切片的 DELETE 任务。"""

        return await self._ensure_task(
            document=document,
            task_type=KnowledgeIndexTaskTypeEnum.DELETE,
            target_chunk_version=1,
            source="document_archive",
            processing_config=None,
        )

    async def _ensure_task(
        self,
        *,
        document: KnowledgeDocumentModel,
        task_type: KnowledgeIndexTaskTypeEnum,
        target_chunk_version: int,
        source: str,
        processing_config: KnowledgeTextProcessingConfig | None,
    ) -> KnowledgeIndexTaskRegistrationResult:
        if target_chunk_version < 1:
            raise ValueError("target_chunk_version 必须大于 0")
        idempotency_key = self.build_idempotency_key(
            knowledge_base_id=document.knowledge_base_id,
            document_id=document.id,
            task_type=task_type,
            content_hash=document.content_hash,
            target_chunk_version=target_chunk_version,
        )
        existing_task = await self.session.scalar(
            select(KnowledgeIndexTaskModel).where(
                KnowledgeIndexTaskModel.idempotency_key == idempotency_key
            )
        )
        if existing_task is not None:
            return KnowledgeIndexTaskRegistrationResult(
                task=existing_task,
                created=False,
            )

        task_metadata = {"source": source}
        if task_type != KnowledgeIndexTaskTypeEnum.DELETE:
            # 任务保存完整配置快照，重试和异步执行不会受到页面随后修改的影响。
            task_metadata["processing_config"] = (
                processing_config or self.chunker.config
            ).to_dict()
        task = KnowledgeIndexTaskModel(
            idempotency_key=idempotency_key,
            knowledge_base_id=document.knowledge_base_id,
            document_id=document.id,
            task_type=task_type,
            status=KnowledgeIndexTaskStatusEnum.PENDING,
            content_hash=document.content_hash,
            target_chunk_version=target_chunk_version,
            task_metadata=task_metadata,
        )
        self.session.add(task)
        await self.session.flush([task])
        return KnowledgeIndexTaskRegistrationResult(task=task, created=True)

    async def run_task(self, task_id: str) -> KnowledgeIndexExecutionResult:
        """按任务 ID 执行一次索引任务，并在失败时记录失败状态而不抛出。"""

        task = await self.session.scalar(
            select(KnowledgeIndexTaskModel)
            .where(KnowledgeIndexTaskModel.id == task_id)
            .options(
                selectinload(KnowledgeIndexTaskModel.document),
                selectinload(KnowledgeIndexTaskModel.knowledge_base),
            )
        )
        if task is None:
            raise ValueError(f"索引任务不存在：{task_id}")
        return await self.process_task(task)

    async def process_task(
        self,
        task: KnowledgeIndexTaskModel,
    ) -> KnowledgeIndexExecutionResult:
        """执行单个 UPSERT、REBUILD 或 DELETE 任务。"""

        if task.status == KnowledgeIndexTaskStatusEnum.SUCCEEDED:
            return KnowledgeIndexExecutionResult(task_id=task.id, succeeded=True)
        if task.status == KnowledgeIndexTaskStatusEnum.PROCESSING:
            return KnowledgeIndexExecutionResult(
                task_id=task.id,
                succeeded=False,
                error_type="TaskAlreadyProcessing",
            )

        is_retry = task.status == KnowledgeIndexTaskStatusEnum.FAILED
        task.status = KnowledgeIndexTaskStatusEnum.PROCESSING
        task.started_at = datetime.now()
        task.completed_at = None
        task.last_error = None
        if is_retry:
            task.retry_count += 1
        await self.session.flush([task])

        try:
            knowledge_base = self._require_knowledge_base(task)
            definition = self._require_matching_definition(knowledge_base)
            if task.task_type == KnowledgeIndexTaskTypeEnum.DELETE:
                chunk_count = await self._process_delete_task(task, definition)
            elif task.task_type in {
                KnowledgeIndexTaskTypeEnum.UPSERT,
                KnowledgeIndexTaskTypeEnum.REBUILD,
            }:
                chunk_count = await self._process_upsert_task(task, definition)
            else:
                raise ValueError(f"不支持的索引任务类型：{task.task_type}")
        except Exception as error:
            self._mark_task_failed(task, error)
            await self.session.flush([task])
            return KnowledgeIndexExecutionResult(
                task_id=task.id,
                succeeded=False,
                error_type=type(error).__name__,
            )

        task.status = KnowledgeIndexTaskStatusEnum.SUCCEEDED
        task.completed_at = datetime.now()
        task.last_error = None
        task_metadata = dict(task.task_metadata or {})
        task_metadata.update(
            {
                "chunk_count": chunk_count,
            }
        )
        if task.task_type != KnowledgeIndexTaskTypeEnum.DELETE:
            task_metadata["embedding_model"] = self._get_embedding_service().model
        task.task_metadata = task_metadata
        await self.session.flush([task])
        return KnowledgeIndexExecutionResult(
            task_id=task.id,
            succeeded=True,
            chunk_count=chunk_count,
        )

    async def consume_pending_tasks(
        self,
        *,
        limit: int = 20,
    ) -> list[KnowledgeIndexExecutionResult]:
        """按创建时间消费一批待处理任务，供后续调度器或后台任务调用。"""

        if limit < 1:
            raise ValueError("limit 必须大于 0")
        tasks = list(
            await self.session.scalars(
                select(KnowledgeIndexTaskModel)
                .where(KnowledgeIndexTaskModel.status == KnowledgeIndexTaskStatusEnum.PENDING)
                .order_by(KnowledgeIndexTaskModel.created_at.asc())
                .limit(limit)
                .options(
                    selectinload(KnowledgeIndexTaskModel.document),
                    selectinload(KnowledgeIndexTaskModel.knowledge_base),
                )
            )
        )
        return [await self.process_task(task) for task in tasks]

    async def _process_upsert_task(
        self,
        task: KnowledgeIndexTaskModel,
        definition: KnowledgeBaseDefinition,
    ) -> int:
        document = self._require_indexable_document(task)
        source_path = self.file_path_resolver(document.storage_path)
        text_blocks = await asyncio.to_thread(
            self.text_extractor.extract,
            file_path=source_path,
            file_type=document.file_type,
        )
        processing_config = self._get_task_processing_config(task)
        cleaned_text_blocks = await asyncio.to_thread(
            self.text_cleaner.clean,
            text_blocks,
            config=processing_config.cleaning,
        )
        chunker = StructuredKnowledgeChunker.from_config(processing_config)
        chunks = await asyncio.to_thread(
            chunker.chunk,
            document_title=document.title,
            text_blocks=cleaned_text_blocks,
        )
        embedding_service = self._get_embedding_service()
        vectors = await embedding_service.embed_documents(
            [chunk.content for chunk in chunks]
        )
        if len(vectors) != len(chunks):
            raise ValueError(
                f"Embedding 返回数量不匹配：期望 {len(chunks)}，实际 {len(vectors)}"
            )
        self._validate_embedding_vectors(vectors, definition)

        # 同一文档先删除旧切片，再写入新切片，避免更新后旧段落继续被召回。
        self._delete_milvus_document_chunks(
            definition=definition,
            document_id=document.id,
        )
        await self.session.execute(
            delete(KnowledgeDocumentChunkModel).where(
                KnowledgeDocumentChunkModel.document_id == document.id
            )
        )

        persisted_chunks: list[KnowledgeDocumentChunkModel] = []
        target_chunk_version = task.target_chunk_version or 1
        for chunk in chunks:
            persisted_chunk = KnowledgeDocumentChunkModel(
                knowledge_base_id=document.knowledge_base_id,
                document_id=document.id,
                chunk_index=chunk.chunk_index,
                chunk_version=target_chunk_version,
                section_path=chunk.section_path,
                page_number=chunk.page_number,
                content=chunk.content,
                content_hash=chunk.content_hash,
                token_count=chunk.token_count,
            )
            self.session.add(persisted_chunk)
            persisted_chunks.append(persisted_chunk)
        await self.session.flush(persisted_chunks)

        self._get_milvus_client().upsert(
            collection_name=definition.collection_name,
            data=[
                self._build_milvus_row(
                    chunk=chunk,
                    vector=vector,
                    document=document,
                    target_chunk_version=target_chunk_version,
                )
                for chunk, vector in zip(persisted_chunks, vectors, strict=True)
            ],
        )
        document.status = KnowledgeDocumentStatusEnum.ACTIVE
        document.indexed_at = datetime.now()
        return len(persisted_chunks)

    async def _process_delete_task(
        self,
        task: KnowledgeIndexTaskModel,
        definition: KnowledgeBaseDefinition,
    ) -> int:
        document = self._require_task_document(task)
        self._delete_milvus_document_chunks(
            definition=definition,
            document_id=document.id,
        )
        await self.session.execute(
            delete(KnowledgeDocumentChunkModel).where(
                KnowledgeDocumentChunkModel.document_id == document.id
            )
        )
        document.status = KnowledgeDocumentStatusEnum.ARCHIVED
        document.indexed_at = None
        return 0

    def _require_knowledge_base(self, task: KnowledgeIndexTaskModel) -> KnowledgeBaseModel:
        knowledge_base = task.knowledge_base
        if knowledge_base is None:
            raise ValueError(f"索引任务缺少知识库：{task.id}")
        return knowledge_base

    def _require_matching_definition(
        self,
        knowledge_base: KnowledgeBaseModel,
    ) -> KnowledgeBaseDefinition:
        definition = self.knowledge_base_definition
        if definition is None:
            raise ValueError("执行索引任务时必须提供知识库定义")
        if (
            definition.key != knowledge_base.key
            or definition.collection_name != knowledge_base.collection_name
            or definition.schema_version != knowledge_base.schema_version
        ):
            raise ValueError("知识库注册记录与执行定义不一致")
        return definition

    @staticmethod
    def _require_task_document(task: KnowledgeIndexTaskModel) -> KnowledgeDocumentModel:
        if task.document is None:
            raise ValueError(f"索引任务缺少文档：{task.id}")
        return task.document

    def _require_indexable_document(
        self,
        task: KnowledgeIndexTaskModel,
    ) -> KnowledgeDocumentModel:
        document = self._require_task_document(task)
        if document.status == KnowledgeDocumentStatusEnum.ARCHIVED:
            raise ValueError(f"归档文档不能建立索引：{document.id}")
        return document

    def _get_task_processing_config(
        self,
        task: KnowledgeIndexTaskModel,
    ) -> KnowledgeTextProcessingConfig:
        """读取任务创建时固化的处理配置，并兼容历史任务。"""

        task_metadata = task.task_metadata or {}
        raw_config = task_metadata.get("processing_config")
        if raw_config is None:
            return self.chunker.config
        if not isinstance(raw_config, dict):
            raise ValueError("索引任务的文本处理配置格式错误")
        return KnowledgeTextProcessingConfig.from_mapping(raw_config)

    def _validate_embedding_vectors(
        self,
        vectors: list[list[float]],
        definition: KnowledgeBaseDefinition,
    ) -> None:
        if not vectors:
            raise ValueError("Embedding 未返回任何向量")
        invalid_dimensions = [len(vector) for vector in vectors if len(vector) != definition.collection_definition.vector_dim]
        if invalid_dimensions:
            raise ValueError(
                "Embedding维度不匹配："
                f"期望 {definition.collection_definition.vector_dim}，"
                f"实际 {invalid_dimensions[0]}"
            )

    def _build_milvus_row(
        self,
        *,
        chunk: KnowledgeDocumentChunkModel,
        vector: list[float],
        document: KnowledgeDocumentModel,
        target_chunk_version: int,
    ) -> dict:
        """构建严格匹配 recruiting_policy Schema 的 Milvus 写入行。"""

        return {
            "id": chunk.id,
            "content": chunk.content,
            "dense_vector": vector,
            "knowledge_base_id": document.knowledge_base_id,
            "document_id": document.id,
            "title": document.title,
            "category": document.category or "",
            "version": document.version or "",
            "effective_date": (
                document.effective_date.isoformat() if document.effective_date else ""
            ),
            "visibility_scope": document.visibility_scope,
            "section_path": chunk.section_path or "",
            # Milvus 当前 Schema 未声明 nullable；-1 表示原文没有可靠页码。
            "page_number": chunk.page_number if chunk.page_number is not None else -1,
            "chunk_index": chunk.chunk_index,
            "chunk_version": target_chunk_version,
        }

    def _delete_milvus_document_chunks(
        self,
        *,
        definition: KnowledgeBaseDefinition,
        document_id: str,
    ) -> None:
        """按文档删除旧向量，文档 ID 来自数据库而非外部请求。"""

        escaped_document_id = document_id.replace('"', '\\"')
        self._get_milvus_client().delete(
            collection_name=definition.collection_name,
            filter=f'document_id == "{escaped_document_id}"',
        )

    @staticmethod
    def _resolve_local_file_path(storage_path: str) -> Path:
        """在默认本地存储目录中安全解析数据库保存的相对文件路径。"""

        relative_path = PurePosixPath(storage_path)
        root_dir = Path(settings.KNOWLEDGE_DOCUMENT_DIR).resolve()
        if (
            not storage_path
            or relative_path.is_absolute()
            or ".." in relative_path.parts
            or relative_path == PurePosixPath(".")
        ):
            raise ValueError("知识库文件存储路径非法")
        resolved_path = (root_dir / relative_path).resolve()
        if root_dir not in resolved_path.parents:
            raise ValueError("知识库文件存储路径越界")
        return resolved_path

    def _get_embedding_service(self) -> EmbeddingService:
        """按需创建 Embedding 客户端，保持任务登记路径无外部依赖。"""

        if self.embedding_service is None:
            self.embedding_service = EmbeddingService()
        return self.embedding_service

    def _get_milvus_client(self):
        """按需创建 Milvus 客户端，避免登记任务时建立网络连接。"""

        if self.milvus_client is None:
            self.milvus_client = get_milvus_client()
        return self.milvus_client

    @staticmethod
    def _mark_task_failed(task: KnowledgeIndexTaskModel, error: Exception) -> None:
        """记录可审计的错误摘要，避免把文档正文写入任务表或日志。"""

        task.status = KnowledgeIndexTaskStatusEnum.FAILED
        task.completed_at = datetime.now()
        task.last_error = f"{type(error).__name__}: {str(error)}"[:2000]
        if task.document is not None:
            task.document.status = KnowledgeDocumentStatusEnum.INDEX_FAILED

    @staticmethod
    def build_idempotency_key(
        *,
        knowledge_base_id: str,
        document_id: str,
        task_type: KnowledgeIndexTaskTypeEnum,
        content_hash: str,
        target_chunk_version: int,
    ) -> str:
        """生成固定长度的幂等键，避免泄露文档内容或文件路径。"""

        raw_key = "|".join(
            (
                knowledge_base_id,
                document_id,
                task_type.value,
                content_hash,
                str(target_chunk_version),
            )
        )
        return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()
