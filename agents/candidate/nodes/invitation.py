import json
from typing import Any

from services.interview_scheduling_service import InterviewSchedulingService

from ..state import CandidateProcessStage
from .context import get_state_value, load_candidate_runtime_context


def _extract_first_slot_start(tool_result: str) -> str | None:
    """从可用时间工具返回文本中提取第一个推荐开始时间。"""
    prefix = "找到面试官可用的时间："
    if not tool_result.startswith(prefix):
        return None

    slots = json.loads(tool_result.split(prefix, 1)[1])
    if not slots:
        return None
    return slots[0][0]


async def get_available_slots_node(state: Any) -> dict:
    """查询面试官可用时间，并选择第一个时段作为本轮推荐时间。"""
    try:
        context = await load_candidate_runtime_context(state)
        result = await InterviewSchedulingService().get_available_slots(
            context.interviewer
        )
        proposed_time = _extract_first_slot_start(result)
        if not proposed_time:
            return {
                "stage": CandidateProcessStage.NEED_HUMAN_REVIEW,
                "need_human_review": True,
                "last_error": result,
            }
        return {
            "proposed_interview_time": proposed_time,
            "last_error": None,
            "need_human_review": False,
        }
    except Exception as exc:
        return {
            "stage": CandidateProcessStage.NEED_HUMAN_REVIEW,
            "need_human_review": True,
            "last_error": f"获取面试官可用时间失败：{exc}",
        }


async def send_invitation_node(state: Any) -> dict:
    """向候选人发送初步面试时间，随后等待候选人邮件回复。"""
    try:
        context = await load_candidate_runtime_context(state)
        interview_datetime_str = get_state_value(state, "proposed_interview_time")
        if not interview_datetime_str:
            return {
                "stage": CandidateProcessStage.NEED_HUMAN_REVIEW,
                "need_human_review": True,
                "last_error": "发送面试邀请失败：流程缺少 proposed_interview_time",
            }

        result = await InterviewSchedulingService().send_invitation(
            candidate=context.candidate,
            position=context.position,
            interview_datetime_str=interview_datetime_str,
        )
        if "失败" in result:
            return {
                "stage": CandidateProcessStage.NEED_HUMAN_REVIEW,
                "need_human_review": True,
                "last_error": result,
            }
        return {
            "stage": CandidateProcessStage.WAITING_CANDIDATE_REPLY,
            "last_error": None,
            "need_human_review": False,
        }
    except Exception as exc:
        return {
            "stage": CandidateProcessStage.NEED_HUMAN_REVIEW,
            "need_human_review": True,
            "last_error": f"发送面试邀请失败：{exc}",
        }
