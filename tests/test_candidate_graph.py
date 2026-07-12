from agents.candidate.graph import build_candidate_agent
from agents.candidate.nodes.router import route_event, route_reply, route_score
from agents.candidate.state import (
    CandidateAgentState,
    CandidateEventType,
    CandidateReplyIntent,
)


def test_build_candidate_agent_compiles_without_checkpointer():
    graph = build_candidate_agent(checkpointer=None)

    assert graph is not None


def test_route_event_uses_explicit_event_type():
    assert (
        route_event(
            CandidateAgentState(event_type=CandidateEventType.CANDIDATE_CREATED)
        )
        == "candidate_created"
    )
    assert (
        route_event(
            CandidateAgentState(
                event_type=CandidateEventType.CANDIDATE_EMAIL_RECEIVED
            )
        )
        == "candidate_email_received"
    )


def test_route_score_sends_failed_or_missing_score_to_human_review():
    assert route_score(CandidateAgentState(score_passed=True)) == "passed"
    assert route_score(CandidateAgentState(score_passed=False)) == "rejected"
    assert route_score(CandidateAgentState()) == "human_review"


def test_route_reply_maps_candidate_intent():
    assert (
        route_reply(
            CandidateAgentState(candidate_reply_intent=CandidateReplyIntent.CONFIRM)
        )
        == "confirm"
    )
    assert (
        route_reply(
            CandidateAgentState(
                candidate_reply_intent=CandidateReplyIntent.RESCHEDULE,
                candidate_requested_time="2026-07-14T10:00:00+08:00",
            )
        )
        == "reschedule_with_time"
    )
    assert (
        route_reply(
            CandidateAgentState(candidate_reply_intent=CandidateReplyIntent.RESCHEDULE)
        )
        == "reschedule_without_time"
    )
    assert (
        route_reply(
            CandidateAgentState(candidate_reply_intent=CandidateReplyIntent.REFUSE)
        )
        == "refuse"
    )
    assert route_reply(CandidateAgentState()) == "unclear"
