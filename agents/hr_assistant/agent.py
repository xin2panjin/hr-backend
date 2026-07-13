from typing import Any, AsyncIterator

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

    async def astream(
        self,
        messages: list[BaseMessage],
        thread_id: str,
    ) -> AsyncIterator[tuple[str, Any]]:
        """流式执行 Agent，输出模型 token 和 Graph 节点更新事件。

        多 stream_mode 时 LangGraph 会返回 ``(mode, data)`` 元组。应用服务
        负责把内部事件转换成稳定、脱敏的 SSE 协议，避免路由层依赖 LangGraph 格式。
        """

        if self._agent is None:
            raise RuntimeError("HRAssistantAgent must be used as an async context manager")

        async for event in self._agent.astream(
            {
                "messages": messages,
                "current_user_id": self.current_user_id,
            },
            {"configurable": {"thread_id": thread_id}},
            stream_mode=["messages", "updates"],
        ):
            yield event

    async def get_state_values(self, thread_id: str) -> dict:
        """在流执行完成后读取最终 State，用于持久化最终回答和 artifacts。"""

        if self._agent is None:
            raise RuntimeError("HRAssistantAgent must be used as an async context manager")

        snapshot = await self._agent.aget_state(
            {"configurable": {"thread_id": thread_id}}
        )
        return dict(snapshot.values)

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
