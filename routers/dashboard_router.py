from fastapi import APIRouter, Depends
from models import AsyncSessionFactory, AsyncSession
from dependencies import get_session_instance, get_current_user
from models.user import UserModel
from repository.candidate_repo import CandidateRepo
from datetime import datetime, timedelta

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

@router.get("/candidate/7d", summary="获取最近7天系统中新增候选人的数量")
async def get_7d_candidate(
    session: AsyncSession = Depends(get_session_instance),
    _: UserModel = Depends(get_current_user),
):
    async with session.begin():
        candidate_repo = CandidateRepo(session)
        now = datetime.now()
        end_time = datetime(year=now.year, month=now.month, day=now.day)
        start_time = end_time - timedelta(days=6)
        rows = await candidate_repo.candidate_count(
            start_time=start_time,
            end_time=end_time,
        )
        day_counts = {day: count for day, count in rows}
        result = []
        for x in range(7):
            day_x = (start_time + timedelta(days=x)).date()
            result.append({
                "day": day_x.isoformat(),
                "count": day_counts.get(day_x, 0),
            })
        return result
