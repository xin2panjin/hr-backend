from . import BaseRepo
from models.candidate import ResumeModel
from sqlalchemy import select


class ResumeRepo(BaseRepo):
    async def create_resume(self, file_path: str, uploader_id: str) -> ResumeModel:
        resume = ResumeModel(file_path=file_path, uploader_id=uploader_id)
        self.session.add(resume)
        return resume

    async def get_by_id(self, resume_id: str) -> ResumeModel:
        return await self.session.scalar(select(ResumeModel).where(ResumeModel.id == resume_id))