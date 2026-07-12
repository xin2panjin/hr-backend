from langchain_core.messages import HumanMessage

from agents.candidate.nodes.logging import build_graph_log_payload
from agents.candidate.state import (
    CandidateAgentState,
    CandidateEventType,
    CandidateProcessStage,
)


def test_build_graph_log_payload_omits_message_content():
    state = CandidateAgentState(
        candidate_id="candidate-1",
        position_id="position-1",
        interviewer_id="interviewer-1",
        event_type=CandidateEventType.CANDIDATE_CREATED,
        stage=CandidateProcessStage.SCORED,
        overall_score=8,
        messages=[HumanMessage(content="这里是候选人邮件正文，不应该进入日志")],
    )

    payload = build_graph_log_payload(state)

    assert payload["candidate_id"] == "candidate-1"
    assert payload["position_id"] == "position-1"
    assert payload["event_type"] == "candidate_created"
    assert payload["stage"] == "scored"
    assert payload["overall_score"] == 8
    assert "messages" not in payload
    assert "这里是候选人邮件正文" not in str(payload)
