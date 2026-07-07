from fastapi import APIRouter, Depends

from dependencies import get_current_user, get_session_instance
from models import AsyncSession
from models.user import UserModel
from repository.candidate_repo import CandidateRepo
from schemas.talent_search_schema import (
    TalentSearchRequestSchema,
    TalentSearchResponseSchema,
)
from services.talent_search_service import TalentSearchService

router = APIRouter(prefix="/talent-search", tags=["talent-search"])


@router.post("/search", summary="人才库语义检索", response_model=TalentSearchResponseSchema)
async def search_talent_pool(
    search_data: TalentSearchRequestSchema,
    session: AsyncSession = Depends(get_session_instance),
    current_user: UserModel = Depends(get_current_user),
):
    async with session.begin():
        service = TalentSearchService(
            candidate_repo=CandidateRepo(session),
        )
        candidates = await service.search(
            query=search_data.query,
            current_user=current_user,
            top_k=search_data.top_k,
            position_id=search_data.position_id,
            status=search_data.status,
        )
        return {"candidates": candidates}