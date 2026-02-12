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