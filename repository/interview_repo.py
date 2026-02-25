from models.candidate import CandidateModel
from models.interview import InterviewModel
from . import BaseRepo
from typing import Any
from sqlalchemy import select


class InterviewRepo(BaseRepo):
    async def create_interview(self, interview_dict: dict[str, Any]) -> InterviewModel:
        interview = InterviewModel(**interview_dict)
        self.session.add(interview)
        return interview

    async def get_by_id(self, interview_id: str) -> InterviewModel | None:
        return await self.session.scalar(select(InterviewModel).where(InterviewModel.id==interview_id))

    async def get_by_candidate_id(self, candidate_id: str) -> InterviewModel | None:
        stmt = select(InterviewModel).where(InterviewModel.candidate_id==candidate_id)
        return await self.session.scalar(stmt)

    async def update_interview(self, interview_id: str, interview_dict: dict[str, Any]) -> InterviewModel:
        interview = await self.get_by_id(interview_id)
        for key, value in interview_dict.items():
            setattr(interview, key, value)
        await self.session.flush()
        await self.session.refresh(interview)
        return interview