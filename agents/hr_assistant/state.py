from typing import Annotated, TypedDict

from langgraph.graph.message import BaseMessage, add_messages


class HRAssistantState(TypedDict):
    """HR招聘助手上下文状态。

    current_user_id 用于工具侧重新加载用户并做权限校验。
    不直接把 ORM UserModel 放进 state，避免 checkpoint 序列化出问题。
    """

    messages: Annotated[list[BaseMessage], add_messages]
    current_user_id: str