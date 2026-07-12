from typing import Any

from services.interview_scheduling_service import InterviewSchedulingService

from ..state import CandidateProcessStage
from .context import get_state_value, load_candidate_runtime_context


async def confirm_interview_node(state: Any) -> dict:
    """确认最终面试时间；失败时只标记人工处理，不在 Graph 内自动重试。"""
    interview_datetime_str = (
        get_state_value(state, "candidate_requested_time")
        or get_state_value(state, "proposed_interview_time")
    )
    if not interview_datetime_str:
        return {
            "stage": CandidateProcessStage.NEED_HUMAN_REVIEW,
            "need_human_review": True,
            "last_error": "确认面试失败：流程缺少最终面试时间",
        }

    try:
        context = await load_candidate_runtime_context(state)
        result = await InterviewSchedulingService().confirm_interview(
            candidate=context.candidate,
            position=context.position,
            interviewer=context.interviewer,
            interview_datetime_str=interview_datetime_str,
        )
        if "失败" in result:
            return {
                "stage": CandidateProcessStage.NEED_HUMAN_REVIEW,
                "need_human_review": True,
                "last_error": result,
            }
        return {
            "stage": CandidateProcessStage.INTERVIEW_CONFIRMED,
            "proposed_interview_time": interview_datetime_str,
            "last_error": None,
            "need_human_review": False,
        }
    except Exception as exc:
        return {
            "stage": CandidateProcessStage.NEED_HUMAN_REVIEW,
            "need_human_review": True,
            "last_error": f"确认面试失败：{exc}",
        }


async def mark_refused_node(state: Any) -> dict:
    """候选人明确拒绝面试时，更新候选人状态。"""
    candidate_id = get_state_value(state, "candidate_id")
    if not candidate_id:
        return {
            "stage": CandidateProcessStage.NEED_HUMAN_REVIEW,
            "need_human_review": True,
            "last_error": "标记拒绝面试失败：流程缺少 candidate_id",
        }

    result = await InterviewSchedulingService().mark_refused(candidate_id)
    if "失败" in result:
        return {
            "stage": CandidateProcessStage.NEED_HUMAN_REVIEW,
            "need_human_review": True,
            "last_error": result,
        }
    return {
        "stage": CandidateProcessStage.REFUSED,
        "last_error": None,
        "need_human_review": False,
    }
