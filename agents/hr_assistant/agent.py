from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.graph.message import BaseMessage

from settings import settings

from .graph import build_hr_assistant_agent


class HRAssistantAgent:
    """HR招聘智能对话助手。"""

    def __init__(self, current_user_id: str):
        self.current_user_id = current_user_id
        self._checkpointer_conn = None
        self._checkpointer = None
        self._agent = None

    async def ainvoke(self, messages: list[BaseMessage], thread_id: str):
        """在指定会话中追加用户消息并调用 Agent。"""

        if self._agent is None:
            raise RuntimeError("HRAssistantAgent must be used as an async context manager")

        return await self._agent.ainvoke(
            {
                "messages": messages,
                "current_user_id": self.current_user_id,
            },
            {"configurable": {"thread_id": thread_id}},
        )

    async def __aenter__(self):
        self._checkpointer_conn = AsyncPostgresSaver.from_conn_string(
            settings.DATABASE_AGENT_URL
        )
        self._checkpointer = await self._checkpointer_conn.__aenter__()
        await self._checkpointer.setup()
        self._agent = build_hr_assistant_agent(self._checkpointer)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        self._agent = None
        if self._checkpointer_conn is not None:
            await self._checkpointer_conn.__aexit__(exc_type, exc_val, exc_tb)