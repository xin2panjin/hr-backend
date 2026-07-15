"""知识库文件存储与文档登记服务测试。"""

from datetime import date
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pytest

from models.knowledge import (
    KnowledgeDocumentStatusEnum,
    KnowledgeIndexTaskStatusEnum,
    KnowledgeIndexTaskTypeEnum,
)
from services.knowledge_document_service import (
    KnowledgeBaseNotFoundError,
    KnowledgeDocumentService,
    KnowledgeDocumentValidationError,
    LocalKnowledgeFileStorage,
)


class FakeUploadFile:
    """模拟分段读取的上传文件。"""

    def __init__(self, filename: str, chunks: list[bytes]):
        self.filename = filename
        self._chunks = list(chunks)

    async def read(self, size: int = -1) -> bytes:
        if not self._chunks:
            return b""
        return self._chunks.pop(0)


class FakeSession:
    """覆盖本阶段服务所需的最小异步会话能力。"""

    def __init__(
        self,
        knowledge_base=None,
        *,
        existing_index_task=None,
        flush_error: Exception | None = None,
    ):
        self.knowledge_base = knowledge_base
        self.existing_index_task = existing_index_task
        self.flush_error = flush_error
        self.added_models: list[object] = []
        self.flush_calls = 0

    async def scalar(self, statement):
        if "knowledge_index_tasks" in str(statement):
            return self.existing_index_task
        return self.knowledge_base

    def add(self, model) -> None:
        self.added_models.append(model)

    async def flush(self, models) -> None:
        self.flush_calls += 1
        if self.flush_error is not None:
            raise self.flush_error
        for model in models:
            if model.id is None:
                model.id = f"generated-{self.flush_calls}"


def build_knowledge_base():
    return SimpleNamespace(id="knowledge-base-1", key="recruiting_policy")


def build_service(tmp_path: Path, session: FakeSession, *, max_file_size_mb: int = 20):
    return KnowledgeDocumentService(
        session=session,
        storage=LocalKnowledgeFileStorage(str(tmp_path)),
        max_file_size_mb=max_file_size_mb,
        file_id_factory=lambda: UUID("12345678-1234-5678-1234-567812345678"),
    )


@pytest.mark.asyncio
async def test_register_document_stores_file_creates_document_and_pending_task(tmp_path):
    session = FakeSession(build_knowledge_base())
    service = build_service(tmp_path, session)

    result = await service.register_document(
        knowledge_base_key="recruiting_policy",
        source=FakeUploadFile(
            "员工休假制度.md",
            [b"# ", "休假制度".encode("utf-8")],
        ),
        title="员工休假制度",
        category="leave",
        version="V1.0",
        effective_date=date(2026, 1, 1),
        visibility_scope="hr_only",
        created_by="user-1",
    )

    expected_storage_path = "recruiting_policy/12345678123456781234567812345678.md"
    assert result.stored_file.storage_path == expected_storage_path
    assert (tmp_path / expected_storage_path).read_bytes() == b"# \xe4\xbc\x91\xe5\x81\x87\xe5\x88\xb6\xe5\xba\xa6"
    assert result.stored_file.content_hash == "d43cd08e81a8e8fabad51653c9dabd4b659e517ff7c0ee07fc4f153dee96920f"

    document, index_task = session.added_models
    assert document.knowledge_base_id == "knowledge-base-1"
    assert document.file_name == "员工休假制度.md"
    assert document.file_type == "md"
    assert document.status == KnowledgeDocumentStatusEnum.DRAFT
    assert document.created_by == "user-1"
    assert index_task.document_id == "generated-1"
    assert index_task.task_type == KnowledgeIndexTaskTypeEnum.UPSERT
    assert index_task.status == KnowledgeIndexTaskStatusEnum.PENDING
    assert index_task.task_metadata == {
        "source": "document_registration",
        "processing_config": {
            "cleaning": {
                "normalize_whitespace": True,
                "remove_urls_and_emails": False,
                "remove_blockquote_metadata": False,
            },
            "chunking": {
                "max_characters": 500,
                "overlap_characters": 80,
                "strategy": "structured_builtin",
                "custom_separator": "。",
                "recursive_separators": ["\n\n", "\n", "。", "！", "？", "；", ";", "，", ",", " ", ""],
            },
        },
    }


@pytest.mark.asyncio
async def test_register_document_rejects_unknown_knowledge_base_before_writing_file(tmp_path):
    service = build_service(tmp_path, FakeSession(None))

    with pytest.raises(KnowledgeBaseNotFoundError, match="recruiting_policy"):
        await service.register_document(
            knowledge_base_key="recruiting_policy",
            source=FakeUploadFile("制度.md", [b"content"]),
            title="制度",
            created_by="user-1",
        )

    assert list(tmp_path.rglob("*")) == []


@pytest.mark.asyncio
async def test_register_document_rejects_unsupported_extension_before_writing_file(tmp_path):
    service = build_service(tmp_path, FakeSession(build_knowledge_base()))

    with pytest.raises(KnowledgeDocumentValidationError, match="仅支持"):
        await service.register_document(
            knowledge_base_key="recruiting_policy",
            source=FakeUploadFile("制度.xlsx", [b"content"]),
            title="制度",
            created_by="user-1",
        )

    assert list(tmp_path.rglob("*")) == []


@pytest.mark.asyncio
async def test_register_document_rejects_empty_file_before_creating_database_records(tmp_path):
    session = FakeSession(build_knowledge_base())
    service = build_service(tmp_path, session)

    with pytest.raises(KnowledgeDocumentValidationError, match="空文件"):
        await service.register_document(
            knowledge_base_key="recruiting_policy",
            source=FakeUploadFile("制度.txt", []),
            title="制度",
            created_by="user-1",
        )

    assert session.added_models == []
    assert list(tmp_path.rglob("*.txt")) == []


@pytest.mark.asyncio
async def test_register_document_removes_file_when_database_flush_fails(tmp_path):
    service = build_service(
        tmp_path,
        FakeSession(build_knowledge_base(), flush_error=RuntimeError("database error")),
    )

    with pytest.raises(RuntimeError, match="database error"):
        await service.register_document(
            knowledge_base_key="recruiting_policy",
            source=FakeUploadFile("制度.txt", [b"content"]),
            title="制度",
            created_by="user-1",
        )

    assert list(tmp_path.rglob("*.txt")) == []


@pytest.mark.asyncio
async def test_local_storage_rejects_path_traversal_and_oversized_file(tmp_path):
    storage = LocalKnowledgeFileStorage(str(tmp_path))

    with pytest.raises(KnowledgeDocumentValidationError, match="路径非法"):
        await storage.save(
            source=FakeUploadFile("制度.txt", [b"content"]),
            storage_path="../outside.txt",
            max_size_bytes=100,
        )

    with pytest.raises(KnowledgeDocumentValidationError, match="不能超过"):
        await storage.save(
            source=FakeUploadFile("制度.txt", [b"12345"]),
            storage_path="recruiting_policy/policy.txt",
            max_size_bytes=4,
        )

    # 超限失败时允许保留已创建的目录，但不能留下任何临时文件或目标文件。
    assert list(tmp_path.rglob("*.txt")) == []
