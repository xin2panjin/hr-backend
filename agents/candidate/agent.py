from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from settings import settings

from .graph import build_candidate_agent


class CandidateProcessAgent:
    """管理 checkpoint 数据库连接，并调用候选人招聘流程图。"""

    def __init__(self):
        self._checkpointer = None
        self._checkpointer_conn = None
        self._agent = None

    async def ainvoke(self, state: dict, thread_id: str):
        """在指定招聘会话中追加轻量状态并继续执行流程。"""
        if self._agent is None:
            raise RuntimeError("CandidateProcessAgent must be used as an async context manager")

        return await self._agent.ainvoke(
            state,
            {"configurable": {"thread_id": thread_id}},
        )

    async def __aenter__(self):
        """建立 Agent 状态库连接，并完成流程图初始化。"""
        self._checkpointer_conn = AsyncPostgresSaver.from_conn_string(
            settings.DATABASE_AGENT_URL
        )
        self._checkpointer = await self._checkpointer_conn.__aenter__()
        await self._checkpointer.setup()
        self._agent = build_candidate_agent(self._checkpointer)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """释放流程图引用和 checkpoint 数据库连接。"""
        self._agent = None
        if self._checkpointer_conn is not None:
            await self._checkpointer_conn.__aexit__(exc_type, exc_val, exc_tb)
