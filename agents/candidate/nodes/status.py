from typing import Any

from models import AsyncSessionFactory
from models.candidate import CandidateStatusEnum
from repository.candidate_repo import CandidateRepo

from ..state import CandidateProcessStage
from .context import get_state_value


async def mark_ai_rejected_node(state: Any) -> dict:
    """AI 评分不通过时，确保候选人状态为 AI 筛选未通过。"""
    candidate_id = get_state_value(state, "candidate_id")
    if not candidate_id:
        return {
            "stage": CandidateProcessStage.NEED_HUMAN_REVIEW,
            "need_human_review": True,
            "last_error": "标记 AI 筛选未通过失败：流程缺少 candidate_id",
        }

    try:
        async with AsyncSessionFactory() as session:
            async with session.begin():
                await CandidateRepo(session).update_candidate_status(
                    candidate_id=candidate_id,
                    status=CandidateStatusEnum.AI_FILTER_REJECTED,
                )
        return {
            "stage": CandidateProcessStage.AI_REJECTED,
            "last_error": None,
            "need_human_review": False,
        }
    except Exception as exc:
        return {
            "stage": CandidateProcessStage.NEED_HUMAN_REVIEW,
            "need_human_review": True,
            "last_error": f"标记 AI 筛选未通过失败：{exc}",
        }
