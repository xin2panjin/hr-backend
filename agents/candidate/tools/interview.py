from datetime import datetime

from langchain.tools import ToolRuntime, tool

from services.interview_scheduling_service import InterviewSchedulingService

from ..state import CandidateAgentState


@tool
async def get_interviewer_available_slot(
    runtime: ToolRuntime[CandidateAgentState],
) -> str:
    """查询面试官未来七天内可用于面试的一小时时段。"""
    return await InterviewSchedulingService().get_available_slots(
        runtime.state["interviewer"]
    )


@tool
async def send_interview_email(
    interview_datetime_str: str,
    runtime: ToolRuntime[CandidateAgentState],
) -> str:
    """向候选人发送包含初步面试时间的邀请邮件。"""
    return await InterviewSchedulingService().send_invitation(
        candidate=runtime.state["candidate"],
        position=runtime.state["position"],
        interview_datetime_str=interview_datetime_str,
    )


@tool
async def confirm_interview_time(
    interview_datetime_str: str,
    runtime: ToolRuntime[CandidateAgentState],
) -> str:
    """确认面试时间，并同步邮件、钉钉日程和系统面试记录。"""
    return await InterviewSchedulingService().confirm_interview(
        candidate=runtime.state["candidate"],
        position=runtime.state["position"],
        interviewer=runtime.state["interviewer"],
        interview_datetime_str=interview_datetime_str,
    )


@tool
async def refuse_interview(runtime: ToolRuntime[CandidateAgentState]) -> str:
    """将候选人状态更新为拒绝面试。"""
    return await InterviewSchedulingService().mark_refused(
        runtime.state["candidate"].id
    )


@tool
def get_current_time() -> str:
    """返回当前本地时间，帮助模型理解“明天”等相对时间表达。"""
    now = datetime.now()
    weekdays = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]
    return (
        f"{now.year}年{now.month}月{now.day}日 "
        f"{now.hour:02d}:{now.minute:02d}:{now.second:02d} "
        f"{weekdays[now.weekday()]}（本月第{now.day}天）"
    )
