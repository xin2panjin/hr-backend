import pytest

from agents.candidate import graph as graph_module
from agents.candidate.nodes import logging as graph_logging_module
from agents.candidate.state import (
    CandidateEventType,
    CandidateProcessStage,
    CandidateReplyIntent,
)


@pytest.fixture(autouse=True)
def disable_candidate_graph_event_db_write(monkeypatch):
    """Graph 行为测试只验证路由，不真实写业务审计表。"""

    async def fake_record_graph_event(event_data):
        return None

    monkeypatch.setattr(
        graph_logging_module,
        "record_graph_event",
        fake_record_graph_event,
    )


def build_base_state(event_type: CandidateEventType) -> dict:
    """构造 Graph 行为测试使用的轻量输入状态。"""
    return {
        "candidate_id": "candidate-1",
        "position_id": "position-1",
        "interviewer_id": "interviewer-1",
        "event_type": event_type,
        "messages": [{"role": "user", "content": "测试事件"}],
    }


@pytest.mark.asyncio
async def test_candidate_created_passed_score_sends_invitation(monkeypatch):
    calls = []

    async def fake_score_candidate_node(state):
        calls.append("score_candidate")
        return {
            "stage": CandidateProcessStage.SCORED,
            "score_passed": True,
            "overall_score": 9,
        }

    async def fake_get_available_slots_node(state):
        calls.append("get_available_slots")
        return {"proposed_interview_time": "2026-07-14T10:00:00+08:00"}

    async def fake_send_invitation_node(state):
        calls.append("send_invitation")
        return {"stage": CandidateProcessStage.WAITING_CANDIDATE_REPLY}

    monkeypatch.setattr(
        graph_module, "score_candidate_node", fake_score_candidate_node
    )
    monkeypatch.setattr(
        graph_module, "get_available_slots_node", fake_get_available_slots_node
    )
    monkeypatch.setattr(
        graph_module, "send_invitation_node", fake_send_invitation_node
    )

    graph = graph_module.build_candidate_agent(checkpointer=None)
    result = await graph.ainvoke(
        build_base_state(CandidateEventType.CANDIDATE_CREATED)
    )

    assert calls == ["score_candidate", "get_available_slots", "send_invitation"]
    assert result["stage"] == CandidateProcessStage.WAITING_CANDIDATE_REPLY
    assert result["proposed_interview_time"] == "2026-07-14T10:00:00+08:00"


@pytest.mark.asyncio
async def test_candidate_created_rejected_score_marks_ai_rejected(monkeypatch):
    calls = []

    async def fake_score_candidate_node(state):
        calls.append("score_candidate")
        return {
            "stage": CandidateProcessStage.SCORED,
            "score_passed": False,
            "overall_score": 5,
        }

    async def fake_mark_ai_rejected_node(state):
        calls.append("mark_ai_rejected")
        return {"stage": CandidateProcessStage.AI_REJECTED}

    monkeypatch.setattr(
        graph_module, "score_candidate_node", fake_score_candidate_node
    )
    monkeypatch.setattr(
        graph_module, "mark_ai_rejected_node", fake_mark_ai_rejected_node
    )

    graph = graph_module.build_candidate_agent(checkpointer=None)
    result = await graph.ainvoke(
        build_base_state(CandidateEventType.CANDIDATE_CREATED)
    )

    assert calls == ["score_candidate", "mark_ai_rejected"]
    assert result["stage"] == CandidateProcessStage.AI_REJECTED


@pytest.mark.asyncio
async def test_candidate_email_confirm_routes_to_confirm_interview(monkeypatch):
    calls = []

    async def fake_parse_candidate_reply_node(state):
        calls.append("parse_candidate_reply")
        return {
            "stage": CandidateProcessStage.REPLY_PARSED,
            "candidate_reply_intent": CandidateReplyIntent.CONFIRM,
            "candidate_requested_time": "2026-07-14T10:00:00+08:00",
        }

    async def fake_confirm_interview_node(state):
        calls.append("confirm_interview")
        return {"stage": CandidateProcessStage.INTERVIEW_CONFIRMED}

    monkeypatch.setattr(
        graph_module, "parse_candidate_reply_node", fake_parse_candidate_reply_node
    )
    monkeypatch.setattr(
        graph_module, "confirm_interview_node", fake_confirm_interview_node
    )

    graph = graph_module.build_candidate_agent(checkpointer=None)
    result = await graph.ainvoke(
        build_base_state(CandidateEventType.CANDIDATE_EMAIL_RECEIVED)
    )

    assert calls == ["parse_candidate_reply", "confirm_interview"]
    assert result["stage"] == CandidateProcessStage.INTERVIEW_CONFIRMED


@pytest.mark.asyncio
async def test_candidate_email_reschedule_with_time_confirms_interview(monkeypatch):
    calls = []

    async def fake_parse_candidate_reply_node(state):
        calls.append("parse_candidate_reply")
        return {
            "stage": CandidateProcessStage.REPLY_PARSED,
            "candidate_reply_intent": CandidateReplyIntent.RESCHEDULE,
            "candidate_requested_time": "2026-07-15T15:00:00+08:00",
        }

    async def fake_confirm_interview_node(state):
        calls.append("confirm_interview")
        return {"stage": CandidateProcessStage.INTERVIEW_CONFIRMED}

    monkeypatch.setattr(
        graph_module, "parse_candidate_reply_node", fake_parse_candidate_reply_node
    )
    monkeypatch.setattr(
        graph_module, "confirm_interview_node", fake_confirm_interview_node
    )

    graph = graph_module.build_candidate_agent(checkpointer=None)
    result = await graph.ainvoke(
        build_base_state(CandidateEventType.CANDIDATE_EMAIL_RECEIVED)
    )

    assert calls == ["parse_candidate_reply", "confirm_interview"]
    assert result["stage"] == CandidateProcessStage.INTERVIEW_CONFIRMED


@pytest.mark.asyncio
async def test_candidate_email_refuse_marks_refused(monkeypatch):
    calls = []

    async def fake_parse_candidate_reply_node(state):
        calls.append("parse_candidate_reply")
        return {
            "stage": CandidateProcessStage.REPLY_PARSED,
            "candidate_reply_intent": CandidateReplyIntent.REFUSE,
        }

    async def fake_mark_refused_node(state):
        calls.append("mark_refused")
        return {"stage": CandidateProcessStage.REFUSED}

    monkeypatch.setattr(
        graph_module, "parse_candidate_reply_node", fake_parse_candidate_reply_node
    )
    monkeypatch.setattr(graph_module, "mark_refused_node", fake_mark_refused_node)

    graph = graph_module.build_candidate_agent(checkpointer=None)
    result = await graph.ainvoke(
        build_base_state(CandidateEventType.CANDIDATE_EMAIL_RECEIVED)
    )

    assert calls == ["parse_candidate_reply", "mark_refused"]
    assert result["stage"] == CandidateProcessStage.REFUSED


@pytest.mark.asyncio
async def test_confirm_interview_failure_goes_to_human_review_without_retry(monkeypatch):
    calls = []

    async def fake_parse_candidate_reply_node(state):
        calls.append("parse_candidate_reply")
        return {
            "stage": CandidateProcessStage.REPLY_PARSED,
            "candidate_reply_intent": CandidateReplyIntent.CONFIRM,
            "candidate_requested_time": "2026-07-14T10:00:00+08:00",
        }

    async def fake_confirm_interview_node(state):
        calls.append("confirm_interview")
        return {
            "stage": CandidateProcessStage.NEED_HUMAN_REVIEW,
            "need_human_review": True,
            "last_error": "确认面试失败：数据库写入失败",
        }

    async def fake_human_review_node(state):
        calls.append("human_review")
        return {
            "stage": CandidateProcessStage.NEED_HUMAN_REVIEW,
            "need_human_review": True,
            "last_error": "确认面试失败：数据库写入失败",
        }

    monkeypatch.setattr(
        graph_module, "parse_candidate_reply_node", fake_parse_candidate_reply_node
    )
    monkeypatch.setattr(
        graph_module, "confirm_interview_node", fake_confirm_interview_node
    )
    monkeypatch.setattr(graph_module, "human_review_node", fake_human_review_node)

    graph = graph_module.build_candidate_agent(checkpointer=None)
    result = await graph.ainvoke(
        build_base_state(CandidateEventType.CANDIDATE_EMAIL_RECEIVED)
    )

    assert calls == ["parse_candidate_reply", "confirm_interview", "human_review"]
    assert calls.count("confirm_interview") == 1
    assert result["stage"] == CandidateProcessStage.NEED_HUMAN_REVIEW
    assert result["need_human_review"] is True
