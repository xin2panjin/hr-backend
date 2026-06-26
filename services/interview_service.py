from fastapi import HTTPException

from models import AsyncSession
from models.interview import InterviewModel, InterviewResultEnum
from models.user import UserModel
from repository.interview_repo import InterviewRepo
from schemas.candidate_schema import CandidateStatusUpdateSchema


class InterviewService:
    def __init__(
        self,
        session: AsyncSession,
        interview_repo: InterviewRepo | None = None,
    ):
        self.session = session
        self.interview_repo = interview_repo or InterviewRepo(session)

    async def create_waiting_interview(
        self,
        candidate_id: str,
        status_data: CandidateStatusUpdateSchema,
        current_user: UserModel,
    ) -> None:
        if not status_data.interview_time:
            raise HTTPException(status_code=400, detail="变更为待面试时必须填写面试时间")

        await self.interview_repo.create_interview(
            {
                "scheduled_time": status_data.interview_time,
                "candidate_id": candidate_id,
                "interviewer_id": current_user.id,
            }
        )

    async def mark_interview_rejected(
        self,
        candidate_id: str,
        status_data: CandidateStatusUpdateSchema,
        current_user: UserModel,
    ) -> None:
        if not status_data.rejection_reason:
            raise HTTPException(status_code=400, detail="变更为面试未通过时必须填写未通过原因")

        interview: InterviewModel | None = await self.interview_repo.get_by_candidate_id(candidate_id)
        if interview is not None:
            await self.interview_repo.update_interview(
                interview_id=interview.id,
                interview_dict={
                    "feedback": status_data.rejection_reason,
                    "result": InterviewResultEnum.FAILED,
                },
            )
            return

        await self.interview_repo.create_interview(
            {
                "scheduled_time": status_data.interview_time,
                "feedback": status_data.rejection_reason,
                "result": InterviewResultEnum.FAILED,
                "candidate_id": candidate_id,
                "interviewer_id": current_user.id,
            }
        )
