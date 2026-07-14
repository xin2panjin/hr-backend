import os
from pathlib import Path
from uuid import uuid4

import aiofiles
from fastapi import HTTPException, UploadFile, status
from loguru import logger

from core.cache import HRCache
from core.pdf import WordToPdfConverter
from models import AsyncSession
from models.candidate import ResumeModel
from models.user import UserModel
from repository.candidate_repo import ResumeRepo
from schemas.cache_schema import ResumeParseTaskOwnerSchema, TaskInfoSchema
from settings import settings
from iam.policies.resume_policy import ResumePolicy


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

    async def create_parse_task(
        self,
        *,
        resume_id: str,
        current_user: UserModel,
    ) -> str:
        """校验简历归属后创建可追溯的解析任务。"""

        if self.resume_repo is None:
            raise RuntimeError("resume_repo is required to create a parse task")

        resume: ResumeModel | None = await self.resume_repo.get_by_id(resume_id)
        if not resume:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="简历不存在")
        ResumePolicy.ensure_can_parse(current_user, resume)

        if self.cache is None:
            self.cache = HRCache()

        task_id = self.create_parse_task_id()
        # 先写入 pending 和归属信息，再提交 BackgroundTask，避免任务执行过快时
        # 查询接口看不到任务或无法判断任务归属。
        await self.cache.set_task_info(TaskInfoSchema(task_id=task_id, status="pending"))
        await self.cache.set_resume_parse_task_owner(
            ResumeParseTaskOwnerSchema(
                task_id=task_id,
                owner_id=current_user.id,
                resume_id=resume.id,
            )
        )
        return task_id

    async def get_parse_task_info(
        self,
        task_id: str,
        current_user: UserModel,
    ) -> TaskInfoSchema:
        if self.cache is None:
            self.cache = HRCache()

        task_info = await self.cache.get_task_info(task_id)
        if not task_info:
            raise HTTPException(status_code=404, detail="任务不存在或已过期")

        task_owner = await self.cache.get_resume_parse_task_owner(task_id)
        # 旧任务或异常任务没有归属记录时，默认拒绝读取，不能把 task_id 当成凭证。
        if not task_owner:
            raise HTTPException(status_code=404, detail="任务不存在或已过期")
        ResumePolicy.ensure_can_read_task(current_user, task_owner.owner_id)
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
