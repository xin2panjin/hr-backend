from typing import Any

from ..state import (
    CandidateEventType,
    CandidateProcessStage,
    CandidateReplyIntent,
)
from .context import get_state_value
from .logging import log_route


async def route_event_node(state: Any) -> dict:
    """流程入口节点：保留当前状态，由条件边决定下一步。"""
    return {}


def route_event(state: Any) -> str:
    """根据外部事件类型选择招聘流程入口。"""
    event_type = get_state_value(state, "event_type")
    if event_type == CandidateEventType.CANDIDATE_CREATED:
        decision = "candidate_created"
        log_route("route_event", state, decision)
        return decision
    if event_type == CandidateEventType.CANDIDATE_EMAIL_RECEIVED:
        decision = "candidate_email_received"
        log_route("route_event", state, decision)
        return decision
    decision = "human_review"
    log_route("route_event", state, decision)
    return decision


async def route_score_node(state: Any) -> dict:
    """评分路由占位节点，条件边会根据评分结果继续流转。"""
    return {}


def route_score(state: Any) -> str:
    """根据 AI 评分结果决定邀约或淘汰。"""
    if get_state_value(state, "need_human_review"):
        decision = "human_review"
        log_route("route_score", state, decision)
        return decision
    if get_state_value(state, "score_passed") is True:
        decision = "passed"
        log_route("route_score", state, decision)
        return decision
    if get_state_value(state, "score_passed") is False:
        decision = "rejected"
        log_route("route_score", state, decision)
        return decision
    decision = "human_review"
    log_route("route_score", state, decision)
    return decision


async def route_reply_node(state: Any) -> dict:
    """候选人回复路由占位节点，条件边会根据回复意图继续流转。"""
    return {}


def route_reply(state: Any) -> str:
    """根据候选人邮件回复意图选择后续动作。"""
    if get_state_value(state, "need_human_review"):
        decision = "human_review"
        log_route("route_reply", state, decision)
        return decision

    intent = get_state_value(state, "candidate_reply_intent")
    requested_time = get_state_value(state, "candidate_requested_time")

    if intent == CandidateReplyIntent.CONFIRM:
        decision = "confirm"
        log_route("route_reply", state, decision)
        return decision
    if intent == CandidateReplyIntent.RESCHEDULE and requested_time:
        decision = "reschedule_with_time"
        log_route("route_reply", state, decision)
        return decision
    if intent == CandidateReplyIntent.RESCHEDULE:
        decision = "reschedule_without_time"
        log_route("route_reply", state, decision)
        return decision
    if intent == CandidateReplyIntent.REFUSE:
        decision = "refuse"
        log_route("route_reply", state, decision)
        return decision
    decision = "unclear"
    log_route("route_reply", state, decision)
    return decision


def is_need_human_review(state: Any) -> str:
    """副作用节点结束后的统一路由：失败进入人工处理，成功结束。"""
    if get_state_value(state, "need_human_review"):
        decision = "human_review"
        log_route("is_need_human_review", state, decision)
        return decision
    decision = "done"
    log_route("is_need_human_review", state, decision)
    return decision
