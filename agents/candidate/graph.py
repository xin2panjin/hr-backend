from typing import Any

from langgraph.graph import END, START, StateGraph

from .nodes.confirmation import confirm_interview_node, mark_refused_node
from .nodes.human_review import human_review_node
from .nodes.invitation import get_available_slots_node, send_invitation_node
from .nodes.logging import log_node
from .nodes.reply_parser import parse_candidate_reply_node
from .nodes.router import (
    is_need_human_review,
    route_event,
    route_event_node,
    route_reply,
    route_reply_node,
    route_score,
    route_score_node,
)
from .nodes.scoring import score_candidate_node
from .nodes.status import mark_ai_rejected_node
from .state import CandidateAgentState


def build_candidate_agent(checkpointer: Any):
    """组装显式 LangGraph 候选人招聘流程。

    Graph 负责流程编排；节点负责单步动作；业务数据只按 ID 在节点内加载，
    不把候选人、职位、面试官等大对象写入 checkpoint。
    """
    graph = StateGraph(CandidateAgentState)

    graph.add_node("route_event", log_node("route_event", route_event_node))
    graph.add_node("score_candidate", log_node("score_candidate", score_candidate_node))
    graph.add_node("route_score", log_node("route_score", route_score_node))
    graph.add_node("mark_ai_rejected", log_node("mark_ai_rejected", mark_ai_rejected_node))
    graph.add_node("get_available_slots", log_node("get_available_slots", get_available_slots_node))
    graph.add_node("send_invitation", log_node("send_invitation", send_invitation_node))
    graph.add_node("parse_candidate_reply", log_node("parse_candidate_reply", parse_candidate_reply_node))
    graph.add_node("route_reply", log_node("route_reply", route_reply_node))
    graph.add_node("confirm_interview", log_node("confirm_interview", confirm_interview_node))
    graph.add_node("mark_refused", log_node("mark_refused", mark_refused_node))
    graph.add_node("human_review", log_node("human_review", human_review_node))

    graph.add_edge(START, "route_event")

    graph.add_conditional_edges(
        "route_event",
        route_event,
        {
            "candidate_created": "score_candidate",
            "candidate_email_received": "parse_candidate_reply",
            "human_review": "human_review",
        },
    )

    graph.add_edge("score_candidate", "route_score")
    graph.add_conditional_edges(
        "route_score",
        route_score,
        {
            "passed": "get_available_slots",
            "rejected": "mark_ai_rejected",
            "human_review": "human_review",
        },
    )

    graph.add_edge("get_available_slots", "send_invitation")
    graph.add_conditional_edges(
        "send_invitation",
        is_need_human_review,
        {
            "done": END,
            "human_review": "human_review",
        },
    )
    graph.add_conditional_edges(
        "mark_ai_rejected",
        is_need_human_review,
        {
            "done": END,
            "human_review": "human_review",
        },
    )

    graph.add_edge("parse_candidate_reply", "route_reply")
    graph.add_conditional_edges(
        "route_reply",
        route_reply,
        {
            "confirm": "confirm_interview",
            "reschedule_with_time": "confirm_interview",
            "reschedule_without_time": "get_available_slots",
            "refuse": "mark_refused",
            "unclear": "human_review",
            "human_review": "human_review",
        },
    )

    graph.add_conditional_edges(
        "confirm_interview",
        is_need_human_review,
        {
            "done": END,
            "human_review": "human_review",
        },
    )
    graph.add_conditional_edges(
        "mark_refused",
        is_need_human_review,
        {
            "done": END,
            "human_review": "human_review",
        },
    )
    graph.add_edge("human_review", END)

    return graph.compile(checkpointer=checkpointer)
