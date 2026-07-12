from sqlalchemy import Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from . import BaseModel


class CandidateAgentEventModel(BaseModel):
    """候选人 Agent Graph 执行业务审计事件。

    这张表用于业务排查和审计，不参与 LangGraph checkpoint 恢复。
    """

    __tablename__ = "candidate_agent_events"

    thread_id: Mapped[str | None] = mapped_column(String(255), index=True)
    candidate_id: Mapped[str | None] = mapped_column(String(100), index=True)
    position_id: Mapped[str | None] = mapped_column(String(100), index=True)
    interviewer_id: Mapped[str | None] = mapped_column(String(100), index=True)

    event_type: Mapped[str | None] = mapped_column(String(64), index=True)
    node_name: Mapped[str] = mapped_column(String(128), nullable=False, index=True)

    # node_enter / node_exit / node_error / route
    action_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)

    # started / succeeded / failed / need_human_review / routed
    status: Mapped[str] = mapped_column(String(64), nullable=False, index=True)

    stage_before: Mapped[str | None] = mapped_column(String(64), nullable=True)
    stage_after: Mapped[str | None] = mapped_column(String(64), nullable=True)

    route_decision: Mapped[str | None] = mapped_column(String(128), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    input_summary: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    output_summary: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
