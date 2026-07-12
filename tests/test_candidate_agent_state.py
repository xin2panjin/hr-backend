from agents.candidate.state import (
    CandidateAgentState,
    CandidateEventType,
    CandidateProcessStage,
    CandidateReplyIntent,
)


def test_candidate_agent_state_is_lightweight():
    """候选人流程状态只保存 ID 和流程字段，不持久化完整业务对象。"""
    fields = set(CandidateAgentState.model_fields)

    assert {"candidate_id", "position_id", "interviewer_id"}.issubset(fields)
    assert "candidate" not in fields
    assert "position" not in fields
    assert "interviewer" not in fields


def test_candidate_agent_state_defaults_to_initialized_stage():
    state = CandidateAgentState()

    assert state.stage == CandidateProcessStage.INITIALIZED
    assert state.messages == []
    assert state.need_human_review is False


def test_candidate_agent_state_supports_process_enums():
    state = CandidateAgentState(
        candidate_id="candidate-1",
        position_id="position-1",
        interviewer_id="interviewer-1",
        event_type=CandidateEventType.CANDIDATE_CREATED,
        candidate_reply_intent=CandidateReplyIntent.CONFIRM,
    )

    assert state.event_type == CandidateEventType.CANDIDATE_CREATED
    assert state.candidate_reply_intent == CandidateReplyIntent.CONFIRM
