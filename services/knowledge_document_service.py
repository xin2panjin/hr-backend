"""知识库原始文件存储与文档登记服务。"""

import asyncio
import hashlib
import os
from dataclasses import dataclass
from datetime import date
from pathlib import Path, PurePosixPath
from typing import Protocol
from uuid import uuid4

import aiofiles
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.knowledge import (
    KnowledgeBaseModel,
    KnowledgeBaseStatusEnum,
    KnowledgeDocumentModel,
    KnowledgeDocumentStatusEnum,
    KnowledgeIndexTaskModel,
    KnowledgeIndexTaskTypeEnum,
)
from services.knowledge_index_service import KnowledgeIndexService
from services.knowledge_text_processing import KnowledgeTextProcessingConfig
from settings import settings


class KnowledgeDocumentValidationError(ValueError):
    """上传文件或文档登记参数不符合知识库约束。"""


class KnowledgeBaseNotFoundError(ValueError):
    """请求的知识库尚未由后端注册，或当前已归档。"""


@dataclass(frozen=True, slots=True)
class StoredKnowledgeFile:
    """文件存储层返回的最小、可审计文件信息。"""

    storage_path: str
    content_hash: str
    size_bytes: int


class AsyncReadableFile(Protocol):
    """兼容 FastAPI UploadFile 的最小异步读取接口。"""

    filename: str | None

    async def read(self, size: int = -1) -> bytes:
        """读取下一段文件字节。"""


class KnowledgeFileStorage(Protocol):
    """原始文件存储抽象，后续可替换为 OSS、S3 等实现。"""

    async def save(
        self,
        *,
        source: AsyncReadableFile,
        storage_path: str,
        max_size_bytes: int,
    ) -> StoredKnowledgeFile:
        """保存文件并返回相对路径、内容哈希和大小。"""

    async def delete(self, storage_path: str) -> None:
        """删除文件；不存在时保持幂等。"""


class LocalKnowledgeFileStorage:
    """本地磁盘实现。

    ``storage_path`` 始终是相对根目录的 POSIX 路径，不接收来自客户端的
    路径片段，从而避免目录穿越；写入采用临时文件再原子替换。
    """

    CHUNK_SIZE = 1024 * 1024

    def __init__(self, root_dir: str):
        self.root_dir = Path(root_dir).resolve()

    async def save(
        self,
        *,
        source: AsyncReadableFile,
        storage_path: str,
        max_size_bytes: int,
    ) -> StoredKnowledgeFile:
        relative_path = self._validate_storage_path(storage_path)
        target_path = self.root_dir / relative_path
        temporary_path = target_path.with_name(f".{target_path.name}.uploading")
        await asyncio.to_thread(target_path.parent.mkdir, parents=True, exist_ok=True)

        content_hasher = hashlib.sha256()
        size_bytes = 0
        try:
            async with aiofiles.open(temporary_path, mode="wb") as file_pointer:
                while chunk := await source.read(self.CHUNK_SIZE):
                    size_bytes += len(chunk)
                    if size_bytes > max_size_bytes:
                        raise KnowledgeDocumentValidationError(
                            f"文件大小不能超过 {max_size_bytes // 1024 // 1024} MB"
                        )
                    content_hasher.update(chunk)
                    await file_pointer.write(chunk)
            if size_bytes == 0:
                raise KnowledgeDocumentValidationError("不能上传空文件")
            await asyncio.to_thread(os.replace, temporary_path, target_path)
        except Exception:
            await self._delete_path_if_exists(temporary_path)
            raise

        return StoredKnowledgeFile(
            storage_path=relative_path.as_posix(),
            content_hash=content_hasher.hexdigest(),
            size_bytes=size_bytes,
        )

    async def delete(self, storage_path: str) -> None:
        """删除相对路径对应的文件，不影响其他知识库文件。"""

        relative_path = self._validate_storage_path(storage_path)
        await self._delete_path_if_exists(self.root_dir / relative_path)

    def _validate_storage_path(self, storage_path: str) -> PurePosixPath:
        relative_path = PurePosixPath(storage_path)
        if (
            not storage_path
            or relative_path.is_absolute()
            or ".." in relative_path.parts
            or relative_path == PurePosixPath(".")
        ):
            raise KnowledgeDocumentValidationError("文件存储路径非法")
        return relative_path

    @staticmethod
    async def _delete_path_if_exists(path: Path) -> None:
        try:
            await asyncio.to_thread(path.unlink)
        except FileNotFoundError:
            return


@dataclass(frozen=True, slots=True)
class RegisteredKnowledgeDocument:
    """文档登记成功后，供 API 或后台任务使用的结果。"""

    document: KnowledgeDocumentModel
    index_task: KnowledgeIndexTaskModel
    stored_file: StoredKnowledgeFile


class KnowledgeDocumentService:
    """保存原始文件、登记元数据并创建待处理索引任务。"""

    ALLOWED_EXTENSIONS = {".pdf", ".docx", ".md", ".markdown", ".txt"}

    def __init__(
        self,
        *,
        session: AsyncSession,
        storage: KnowledgeFileStorage | None = None,
        max_file_size_mb: int | None = None,
        file_id_factory=uuid4,
    ):
        self.session = session
        self.storage = storage or LocalKnowledgeFileStorage(settings.KNOWLEDGE_DOCUMENT_DIR)
        configured_max_size_mb = (
            max_file_size_mb
            if max_file_size_mb is not None
            else settings.KNOWLEDGE_DOCUMENT_MAX_FILE_SIZE_MB
        )
        if configured_max_size_mb < 1:
            raise ValueError("max_file_size_mb 必须大于 0")
        self.max_file_size_bytes = configured_max_size_mb * 1024 * 1024
        self.file_id_factory = file_id_factory

    async def register_document(
        self,
        *,
        knowledge_base_key: str,
        source: AsyncReadableFile,
        title: str,
        created_by: str | None,
        category: str | None = None,
        version: str | None = None,
        effective_date: date | None = None,
        visibility_scope: str = "hr_only",
        processing_config: KnowledgeTextProcessingConfig | None = None,
    ) -> RegisteredKnowledgeDocument:
        """登记一份待索引知识文档。

        该方法不解析正文，也不写入 Milvus。它只保存原始文件、写入文档事实
        记录，并在同一数据库会话内创建 ``pending`` 的 UPSERT 索引任务。
        """

        knowledge_base = await self._get_active_knowledge_base(knowledge_base_key)
        normalized_title = self.normalize_required_text(title, "文档标题", max_length=200)
        normalized_visibility_scope = self.normalize_required_text(
            visibility_scope,
            "可见范围",
            max_length=64,
        )
        normalized_file_name, file_extension = self.validate_source_file(source)
        storage_path = self._build_storage_path(knowledge_base.key, file_extension)
        stored_file = await self.storage.save(
            source=source,
            storage_path=storage_path,
            max_size_bytes=self.max_file_size_bytes,
        )

        try:
            document = KnowledgeDocumentModel(
                knowledge_base_id=knowledge_base.id,
                title=normalized_title,
                category=self._normalize_optional_text(category, "文档分类", max_length=64),
                storage_path=stored_file.storage_path,
                file_name=normalized_file_name,
                file_type=file_extension.lstrip("."),
                version=self._normalize_optional_text(version, "文档版本", max_length=64),
                effective_date=effective_date,
                status=KnowledgeDocumentStatusEnum.DRAFT,
                visibility_scope=normalized_visibility_scope,
                content_hash=stored_file.content_hash,
                created_by=created_by,
                updated_by=created_by,
            )
            self.session.add(document)
            # 先取得 document.id，才能让索引任务可靠关联对应文档。
            await self.session.flush([document])

            index_task = (
                await KnowledgeIndexService(self.session).ensure_upsert_task(
                    document=document,
                    processing_config=processing_config,
                )
            ).task
        except Exception:
            # 文件系统不参与数据库事务。登记失败时主动清理刚写入的文件，
            # 防止生成无法被业务表追溯的孤儿文件。
            await self.storage.delete(stored_file.storage_path)
            raise

        return RegisteredKnowledgeDocument(
            document=document,
            index_task=index_task,
            stored_file=stored_file,
        )

    async def _get_active_knowledge_base(self, knowledge_base_key: str) -> KnowledgeBaseModel:
        normalized_key = self.normalize_required_text(
            knowledge_base_key,
            "知识库 key",
            max_length=64,
        )
        knowledge_base = await self.session.scalar(
            select(KnowledgeBaseModel).where(
                KnowledgeBaseModel.key == normalized_key,
                KnowledgeBaseModel.status == KnowledgeBaseStatusEnum.ACTIVE,
            )
        )
        if knowledge_base is None:
            raise KnowledgeBaseNotFoundError(f"未找到可用知识库：{normalized_key}")
        return knowledge_base

    async def list_documents(
        self,
        *,
        knowledge_base_key: str,
        page: int,
        size: int,
        document_status: KnowledgeDocumentStatusEnum | None = None,
    ) -> tuple[list[KnowledgeDocumentModel], int]:
        """分页读取一个受控知识库中的文档，不允许跨库枚举。"""

        knowledge_base = await self._get_active_knowledge_base(knowledge_base_key)
        filters = [KnowledgeDocumentModel.knowledge_base_id == knowledge_base.id]
        if document_status is not None:
            filters.append(KnowledgeDocumentModel.status == document_status)
        documents = list(
            await self.session.scalars(
                select(KnowledgeDocumentModel)
                .where(*filters)
                .order_by(KnowledgeDocumentModel.updated_at.desc())
                .offset((page - 1) * size)
                .limit(size)
            )
        )
        total = int(
            await self.session.scalar(
                select(func.count(KnowledgeDocumentModel.id)).where(*filters)
            )
            or 0
        )
        return documents, total

    async def request_rebuild(
        self,
        *,
        knowledge_base_key: str,
        document_id: str,
        actor_id: str,
        processing_config: KnowledgeTextProcessingConfig | None = None,
    ) -> KnowledgeIndexTaskModel:
        """为当前文档创建新的切片版本与 REBUILD 任务。"""

        document = await self._get_document(knowledge_base_key, document_id)
        if document.status == KnowledgeDocumentStatusEnum.ARCHIVED:
            raise KnowledgeDocumentValidationError("归档文档不能重建索引")
        document.updated_by = actor_id
        from models.knowledge import KnowledgeDocumentChunkModel

        latest_version = await self.session.scalar(
            select(func.max(KnowledgeDocumentChunkModel.chunk_version)).where(
                KnowledgeDocumentChunkModel.document_id == document.id
            )
        )
        result = await KnowledgeIndexService(self.session).ensure_rebuild_task(
            document=document,
            target_chunk_version=int(latest_version or 0) + 1,
            processing_config=(
                processing_config
                or await self._get_latest_processing_config(document.id)
            ),
        )
        return result.task

    async def archive_document(
        self,
        *,
        knowledge_base_key: str,
        document_id: str,
        actor_id: str,
    ) -> KnowledgeIndexTaskModel:
        """先从业务可见范围归档文档，再创建删除索引任务。"""

        document = await self._get_document(knowledge_base_key, document_id)
        document.status = KnowledgeDocumentStatusEnum.ARCHIVED
        document.updated_by = actor_id
        result = await KnowledgeIndexService(self.session).ensure_delete_task(document=document)
        return result.task

    async def _get_document(
        self,
        knowledge_base_key: str,
        document_id: str,
    ) -> KnowledgeDocumentModel:
        knowledge_base = await self._get_active_knowledge_base(knowledge_base_key)
        document = await self.session.scalar(
            select(KnowledgeDocumentModel).where(
                KnowledgeDocumentModel.id == document_id,
                KnowledgeDocumentModel.knowledge_base_id == knowledge_base.id,
            )
        )
        if document is None:
            raise KnowledgeDocumentValidationError("制度文档不存在")
        return document

    def _build_storage_path(self, knowledge_base_key: str, file_extension: str) -> str:
        """生成不含用户文件名的稳定相对路径。"""

        generated_file_id = self.file_id_factory()
        file_id = getattr(generated_file_id, "hex", None)
        if not file_id:
            file_id = str(generated_file_id).replace("-", "")
        if not file_id:
            raise RuntimeError("文件 ID 生成失败")
        return f"{knowledge_base_key}/{file_id}{file_extension}"

    @staticmethod
    def validate_source_file(source: AsyncReadableFile) -> tuple[str, str]:
        """校验上传文件名和类型，供预览与正式上传复用。"""

        raw_file_name = Path(source.filename or "").name.strip()
        if not raw_file_name:
            raise KnowledgeDocumentValidationError("文件名不能为空")
        if len(raw_file_name) > 255:
            raise KnowledgeDocumentValidationError("文件名不能超过 255 个字符")
        file_extension = Path(raw_file_name).suffix.lower()
        if file_extension not in KnowledgeDocumentService.ALLOWED_EXTENSIONS:
            supported_extensions = ", ".join(
                sorted(KnowledgeDocumentService.ALLOWED_EXTENSIONS)
            )
            raise KnowledgeDocumentValidationError(
                f"仅支持以下文档类型：{supported_extensions}"
            )
        return raw_file_name, file_extension

    @staticmethod
    def normalize_required_text(value: str, field_name: str, *, max_length: int) -> str:
        """校验必填文本，供预览、上传和服务层内部共同使用。"""

        normalized_value = value.strip()
        if not normalized_value:
            raise KnowledgeDocumentValidationError(f"{field_name}不能为空")
        if len(normalized_value) > max_length:
            raise KnowledgeDocumentValidationError(
                f"{field_name}不能超过 {max_length} 个字符"
            )
        return normalized_value

    @staticmethod
    def _normalize_optional_text(
        value: str | None,
        field_name: str,
        *,
        max_length: int,
    ) -> str | None:
        if value is None:
            return None
        return KnowledgeDocumentService.normalize_required_text(
            value,
            field_name,
            max_length=max_length,
        )

    async def _get_latest_processing_config(
        self,
        document_id: str,
    ) -> KnowledgeTextProcessingConfig:
        """重建时继承最近任务的处理配置，历史任务则使用默认值。"""

        latest_task = await self.session.scalar(
            select(KnowledgeIndexTaskModel)
            .where(
                KnowledgeIndexTaskModel.document_id == document_id,
                KnowledgeIndexTaskModel.task_type.in_(
                    [
                        KnowledgeIndexTaskTypeEnum.UPSERT,
                        KnowledgeIndexTaskTypeEnum.REBUILD,
                    ]
                ),
            )
            .order_by(KnowledgeIndexTaskModel.created_at.desc())
        )
        raw_config = (latest_task.task_metadata or {}).get("processing_config") if latest_task else None
        if raw_config is None:
            return KnowledgeTextProcessingConfig.from_mapping(None)
        if not isinstance(raw_config, dict):
            raise KnowledgeDocumentValidationError("历史索引任务的文本处理配置无效")
        return KnowledgeTextProcessingConfig.from_mapping(raw_config)
