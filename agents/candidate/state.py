from typing import Annotated, List, Optional, TypeVar

from langgraph.graph.message import BaseMessage, add_messages
from pydantic import BaseModel

from schemas.candidate_schema import CandidateSchema
from schemas.position_schema import PositionSchema
from schemas.user_schema import UserSchema


T = TypeVar("T")


def keep_previous_value(left: T, right: Optional[T]) -> T:
    """本次未传业务对象时，保留 checkpoint 中上一次保存的数据。"""
    return right if right is not None else left


class CandidateAgentState(BaseModel):
    """招聘 Agent 的持久化状态，包括对话消息及招聘流程所需业务上下文。"""

    messages: Annotated[List[BaseMessage], add_messages]
    candidate: Annotated[CandidateSchema, keep_previous_value]
    position: Annotated[PositionSchema, keep_previous_value]
    interviewer: Annotated[UserSchema, keep_previous_value]
