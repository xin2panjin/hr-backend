from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from core.cache import TaskInfoSchema
from schemas.agent_schema import AgentCandidateSchema
from services.resume_service import ResumeService


class FakeResumeRepo:
    def __init__(self):
        self.created_resumes = []

    async def create_resume(self, file_path: str, uploader_id: str):
        self.created_resumes.append((file_path, uploader_id))
        return SimpleNamespace(id="resume-1", file_path=file_path, uploader_id=uploader_id)


class FakeUploadFile:
    def __init__(self, filename: str, content_type: str, chunks: list[bytes]):
        self.filename = filename
        self.content_type = content_type
        self._chunks = list(chunks)

    async def read(self, size: int = -1):
        if not self._chunks:
            return b""
        return self._chunks.pop(0)


class FakeConverter:
    calls = []

    def __init__(self, word_path: str, *, output_pdf_path: str):
        self.word_path = word_path
        self.output_pdf_path = output_pdf_path
        self.__class__.calls.append((word_path, output_pdf_path))

    async def convert(self):
        with open(self.output_pdf_path, "wb") as fp:
            fp.write(b"%PDF")


class FailingConverter(FakeConverter):
    async def convert(self):
        raise RuntimeError("convert failed")


class FakeCache:
    def __init__(self, task_info=None):
        self.task_info = task_info

    async def get_task_info(self, task_id: str):
        return self.task_info


def build_user(user_id="user-1"):
    return SimpleNamespace(id=user_id)


@pytest.mark.asyncio
async def test_upload_resume_rejects_unsupported_file_type(tmp_path):
    service = ResumeService(
        session=None,
        resume_repo=FakeResumeRepo(),
        resume_dir=str(tmp_path),
    )
    file = FakeUploadFile("resume.txt", "text/plain", [b"hello"])

    with pytest.raises(HTTPException) as exc_info:
        await service.upload_resume(file, build_user())

    assert exc_info.value.status_code == 400
    assert "不支持" in exc_info.value.detail


@pytest.mark.asyncio
async def test_upload_resume_saves_file_and_creates_resume_record(tmp_path):
    resume_repo = FakeResumeRepo()
    service = ResumeService(
        session=None,
        resume_repo=resume_repo,
        resume_dir=str(tmp_path),
        filename_factory=lambda: "fixed-id",
    )
    file = FakeUploadFile("resume.pdf", "application/pdf", [b"hello", b" world"])

    resume = await service.upload_resume(file, build_user("user-1"))

    assert (tmp_path / "fixed-id.pdf").read_bytes() == b"hello world"
    assert resume.file_path == "fixed-id.pdf"
    assert resume_repo.created_resumes == [("fixed-id.pdf", "user-1")]


@pytest.mark.asyncio
async def test_upload_resume_converts_word_file_and_stores_pdf_name(tmp_path):
    FakeConverter.calls = []
    resume_repo = FakeResumeRepo()
    service = ResumeService(
        session=None,
        resume_repo=resume_repo,
        resume_dir=str(tmp_path),
        converter_cls=FakeConverter,
        filename_factory=lambda: "fixed-id",
    )
    file = FakeUploadFile(
        "resume.docx",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        [b"word-content"],
    )

    resume = await service.upload_resume(file, build_user("user-1"))

    assert (tmp_path / "fixed-id.docx").read_bytes() == b"word-content"
    assert (tmp_path / "fixed-id.pdf").read_bytes() == b"%PDF"
    assert resume.file_path == "fixed-id.pdf"
    assert resume_repo.created_resumes == [("fixed-id.pdf", "user-1")]
    assert FakeConverter.calls == [
        (str(tmp_path / "fixed-id.docx"), str(tmp_path / "fixed-id.pdf"))
    ]


@pytest.mark.asyncio
async def test_upload_resume_keeps_word_file_when_conversion_fails(tmp_path):
    resume_repo = FakeResumeRepo()
    service = ResumeService(
        session=None,
        resume_repo=resume_repo,
        resume_dir=str(tmp_path),
        converter_cls=FailingConverter,
        filename_factory=lambda: "fixed-id",
    )
    file = FakeUploadFile(
        "resume.doc",
        "application/msword",
        [b"word-content"],
    )

    resume = await service.upload_resume(file, build_user("user-1"))

    assert resume.file_path == "fixed-id.doc"
    assert resume_repo.created_resumes == [("fixed-id.doc", "user-1")]


def test_create_parse_task_id_uses_factory():
    service = ResumeService(
        session=None,
        resume_repo=FakeResumeRepo(),
        task_id_factory=lambda: "task-1",
    )

    assert service.create_parse_task_id() == "task-1"


@pytest.mark.asyncio
async def test_get_parse_task_info_returns_cached_task():
    task_info = TaskInfoSchema(
        task_id="task-1",
        status="done",
        result=AgentCandidateSchema(name="候选人"),
    )
    service = ResumeService(
        session=None,
        resume_repo=FakeResumeRepo(),
        cache=FakeCache(task_info),
    )

    assert await service.get_parse_task_info("task-1") == task_info


@pytest.mark.asyncio
async def test_get_parse_task_info_raises_404_when_missing():
    service = ResumeService(
        session=None,
        resume_repo=FakeResumeRepo(),
        cache=FakeCache(None),
    )

    with pytest.raises(HTTPException) as exc_info:
        await service.get_parse_task_info("missing-task")

    assert exc_info.value.status_code == 404
