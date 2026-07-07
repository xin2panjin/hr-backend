from fastapi import HTTPException

from models import AsyncSession
from models.candidate import CandidateStatusEnum
from models.user import UserModel
from repository.candidate_repo import CandidateRepo
from schemas.candidate_schema import CandidateCreateSchema, CandidateStatusUpdateSchema
from services.interview_service import InterviewService
from repository.candidate_search_repo import (
    CandidateIndexOutboxRepo,
    CandidateSearchProfileRepo,
)
from services.candidate_search_profile_service import CandidateSearchProfileService

class CandidateService:
    STATUS_FLOW = [
        CandidateStatusEnum.APPLICATION,
        CandidateStatusEnum.AI_FILTER_REJECTED,
        CandidateStatusEnum.AI_FILTER_PASSED,
        CandidateStatusEnum.WAITING_FOR_INTERVIEW,
        CandidateStatusEnum.REFUSED_INTERVIEW,
        CandidateStatusEnum.INTERVIEW_PASSED,
        CandidateStatusEnum.INTERVIEW_REJECTED,
        CandidateStatusEnum.HIRED,
        CandidateStatusEnum.REJECTED,
    ]

    def __init__(
        self,
        session: AsyncSession,
        candidate_repo: CandidateRepo | None = None,
        interview_service: InterviewService | None = None,
        search_profile_service: CandidateSearchProfileService | None = None,
    ):
        self.session = session
        self.candidate_repo = candidate_repo or CandidateRepo(session)
        self.interview_service = interview_service or InterviewService(session)
        self.search_profile_service = search_profile_service or CandidateSearchProfileService(
            profile_repo=CandidateSearchProfileRepo(session),
            outbox_repo=CandidateIndexOutboxRepo(session),
        )

    async def create_candidate(
        self,
        candidate_data: CandidateCreateSchema,
        current_user: UserModel,
    ) -> str:
        candidate_dict = candidate_data.model_dump()
        candidate_dict["creator_id"] = current_user.id

        candidate = await self.candidate_repo.create_candidate(candidate_dict)
        # 候选人创建成功后，同步生成脱敏检索画像，并写入索引 outbox。
        # 这里只写 PostgreSQL，不直接调用 Milvus，避免业务事务和向量库强耦合。
        await self.search_profile_service.rebuild_candidate_profile(candidate)
        return candidate.id

    async def update_candidate_status(
        self,
        candidate_id: str,
        status_data: CandidateStatusUpdateSchema,
        current_user: UserModel,
    ) -> None:
        candidate = await self.candidate_repo.get_by_id(candidate_id)
        if not candidate:
            raise HTTPException(status_code=404, detail="候选人不存在")

        self._validate_status_transition(candidate.status, status_data.status)

        if status_data.status == CandidateStatusEnum.WAITING_FOR_INTERVIEW:
            await self.interview_service.create_waiting_interview(candidate_id, status_data, current_user)
        elif status_data.status == CandidateStatusEnum.INTERVIEW_REJECTED:
            await self.interview_service.mark_interview_rejected(candidate_id, status_data, current_user)

        await self.candidate_repo.update_candidate_status(
            candidate_id=candidate_id,
            status=status_data.status,
        )

    def _validate_status_transition(
        self,
        current_status: CandidateStatusEnum,
        target_status: CandidateStatusEnum,
    ) -> None:
        try:
            current_idx = self.STATUS_FLOW.index(current_status)
            target_idx = self.STATUS_FLOW.index(target_status)
        except ValueError:
            raise HTTPException(status_code=400, detail="非法的候选人状态")

        if target_idx <= current_idx:
            raise HTTPException(status_code=400, detail="候选人状态只能往后流转")
