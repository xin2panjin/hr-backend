import os
from pathlib import Path
from uuid import uuid4

import aiofiles
from fastapi import HTTPException, UploadFile, status
from loguru import logger

from core.cache import HRCache
from core.pdf import WordToPdfConverter
from models import AsyncSession
from models.user import UserModel
from repository.candidate_repo import ResumeRepo
from schemas.cache_schema import TaskInfoSchema
from settings import settings


class ResumeService:
    ALLOWED_MIME_TYPES = {
        "application/pdf",
        "application/msword",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "image/jpeg",
        "image/png",
        "image/jpg",
    }
    WORD_EXTENSIONS = {".doc", ".docx"}
    CHUNK_SIZE = 1024 * 1024

    def __init__(
        self,
        session: AsyncSession | None = None,
        resume_repo: ResumeRepo | None = None,
        cache: HRCache | None = None,
        resume_dir: str | None = None,
        converter_cls: type[WordToPdfConverter] = WordToPdfConverter,
        filename_factory=uuid4,
        task_id_factory=uuid4,
    ):
        self.session = session
        self.resume_repo = resume_repo or (ResumeRepo(session) if session is not None else None)
        self.cache = cache
        self.resume_dir = resume_dir or settings.RESUME_DIR
        self.converter_cls = converter_cls
        self.filename_factory = filename_factory
        self.task_id_factory = task_id_factory

    async def upload_resume(self, file: UploadFile, current_user: UserModel):
        if self.resume_repo is None:
            raise RuntimeError("resume_repo is required to upload resume")

        self._validate_upload_file(file)

        file_extension = Path(file.filename or "").suffix
        file_path = await self._save_upload_file(file, file_extension)
        file_path = await self._convert_word_to_pdf_if_needed(file_path, file_extension)

        file_name = Path(file_path).name
        return await self.resume_repo.create_resume(
            file_path=file_name,
            uploader_id=current_user.id,
        )

    def create_parse_task_id(self) -> str:
        return str(self.task_id_factory())

    async def get_parse_task_info(self, task_id: str) -> TaskInfoSchema:
        if self.cache is None:
            self.cache = HRCache()

        task_info = await self.cache.get_task_info(task_id)
        if not task_info:
            raise HTTPException(status_code=404, detail="任务不存在或已过期")
        return task_info

    def _validate_upload_file(self, file: UploadFile) -> None:
        if file.content_type not in self.ALLOWED_MIME_TYPES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="该文件不支持！",
            )

    async def _save_upload_file(self, file: UploadFile, file_extension: str) -> str:
        os.makedirs(self.resume_dir, exist_ok=True)
        unique_filename = f"{self.filename_factory()}{file_extension}"
        file_path = os.path.join(self.resume_dir, unique_filename)

        try:
            async with aiofiles.open(file_path, mode="wb") as fp:
                while content := await file.read(self.CHUNK_SIZE):
                    await fp.write(content)
        except OSError as e:
            logger.error(f"简历保存失败：{e}")
            raise HTTPException(status_code=500, detail="简历保存失败")

        return file_path

    async def _convert_word_to_pdf_if_needed(self, file_path: str, file_extension: str) -> str:
        if file_extension.lower() not in self.WORD_EXTENSIONS:
            return file_path

        pdf_path = str(Path(file_path).with_suffix(".pdf"))
        converter = self.converter_cls(
            word_path=file_path,
            output_pdf_path=pdf_path,
        )
        try:
            await converter.convert()
            return pdf_path
        except Exception as e:
            logger.error(f"Word转PDF失败：{e}")
            return file_path
