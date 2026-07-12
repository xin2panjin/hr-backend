from enum import Enum
from typing import Annotated, Optional, TypeVar

from langgraph.graph.message import BaseMessage, add_messages
from pydantic import BaseModel, Field


T = TypeVar("T")


def keep_previous_value(left: T, right: Optional[T]) -> T:
    """本次未传值时，保留 checkpoint 中上一次保存的流程状态。"""
    return right if right is not None else left


class CandidateEventType(str, Enum):
    """触发候选人流程继续执行的外部事件类型。"""

    CANDIDATE_CREATED = "candidate_created"
    CANDIDATE_EMAIL_RECEIVED = "candidate_email_received"
    MANUAL_RETRY = "manual_retry"


class CandidateProcessStage(str, Enum):
    """候选人招聘流程当前所处阶段。"""

    INITIALIZED = "initialized"
    SCORED = "scored"
    AI_REJECTED = "ai_rejected"
    WAITING_CANDIDATE_REPLY = "waiting_candidate_reply"
    REPLY_PARSED = "reply_parsed"
    INTERVIEW_CONFIRMED = "interview_confirmed"
    REFUSED = "refused"
    NEED_HUMAN_REVIEW = "need_human_review"


class CandidateReplyIntent(str, Enum):
    """候选人邮件回复的结构化意图。"""

    CONFIRM = "confirm"
    RESCHEDULE = "reschedule"
    REFUSE = "refuse"
    UNCLEAR = "unclear"


class CandidateAgentState(BaseModel):
    """候选人招聘流程的轻量持久化状态。

    State 只保存流程身份、阶段和必要中间结果；候选人、职位、面试官等
    业务详情由节点在执行时按 ID 从数据库重新加载，避免 checkpoint 存入大对象。
    """

    messages: Annotated[list[BaseMessage], add_messages] = Field(default_factory=list)

    candidate_id: Annotated[str | None, keep_previous_value] = None
    position_id: Annotated[str | None, keep_previous_value] = None
    interviewer_id: Annotated[str | None, keep_previous_value] = None

    event_type: Annotated[CandidateEventType | None, keep_previous_value] = None
    stage: CandidateProcessStage = CandidateProcessStage.INITIALIZED

    score_passed: bool | None = None
    overall_score: int | None = None
    score_summary: str | None = None

    proposed_interview_time: str | None = None
    candidate_reply_intent: CandidateReplyIntent | None = None
    candidate_requested_time: str | None = None

    last_error: str | None = None
    need_human_review: bool = False
