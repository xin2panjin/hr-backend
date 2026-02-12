from . import BaseRepo
from models.candidate import ResumeModel, CandidateModel
from sqlalchemy import select, update
from models.candidate import CandidateAIScoreModel
from sqlalchemy.orm import selectinload
from models.candidate import CandidateStatusEnum


class ResumeRepo(BaseRepo):
    async def create_resume(self, file_path: str, uploader_id: str) -> ResumeModel:
        resume = ResumeModel(file_path=file_path, uploader_id=uploader_id)
        self.session.add(resume)
        return resume

    async def get_by_id(self, resume_id: str) -> ResumeModel:
        return await self.session.scalar(select(ResumeModel).where(ResumeModel.id == resume_id))


class CandidateRepo(BaseRepo):
    async def create_candidate(self, candidate_info: dict) -> CandidateModel:
        candidate = CandidateModel(**candidate_info)
        self.session.add(candidate)
        await self.session.flush([candidate])
        await self.session.refresh(candidate, ['position', 'resume'])
        return candidate

    async def update_candidate_status(self, candidate_id: str, status: CandidateStatusEnum):
        stmt = update(CandidateModel).where(CandidateModel.id==candidate_id).values(status=status)
        await self.session.execute(stmt)

    async def get_by_id(self, candidate_id: str) -> CandidateModel | None:
        return await self.session.scalar(
            select(CandidateModel)
            .where(CandidateModel.id==candidate_id)
            .options(
                selectinload(CandidateModel.position),
                selectinload(CandidateModel.resume),
                selectinload(CandidateModel.creator)
            )
        )


class CandidateAIScoreRepo(BaseRepo):
    async def create_candidate_score(self, candidate_id: str, candidate_score_dict: dict):
        candidate_score = CandidateAIScoreModel(**candidate_score_dict, candidate_id=candidate_id)
        self.session.add(candidate_score)
        return candidate_score

    async def get_by_candidate_id(self, candidate_id: str):
        return await self.session.scalar(select(CandidateAIScoreModel).where(CandidateAIScoreModel.candidate_id==candidate_id).options(selectinload(CandidateAIScoreModel.candidate)))

    async def update_candidate_status(self, candidate_id: str, status: CandidateStatusEnum):
        candidate_score = self.get_by_candidate_id(candidate_id)
        candidate_score.status = status