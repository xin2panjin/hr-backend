# langchain：好处就是开发简单，不需要判断一些条件；坏处就是消耗token
# langgraph：好处就是很多逻辑写好了，与大模型的交互次数更少，节省token；坏处逻辑判断稍微复杂一些

from langchain.agents import create_agent
from schemas.candidate_schema import CandidateSchema
from schemas.position_schema import PositionSchema
from schemas.user_schema import UserSchema
from langgraph.graph.message import BaseMessage
from .llms import qwen_llm, deepseek_llm
from .prompts import CANDIDATE_PROCESS_SYSTEM_PROMPT
from langchain.agents.middleware import ModelFallbackMiddleware, SummarizationMiddleware
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from settings import settings
from pydantic import BaseModel
from typing import Annotated, List, TypeVar, Optional
from langgraph.graph.message import add_messages

T = TypeVar("T")

def assign_state_property(left: T, right: Optional[T]) -> T:
    return right if right is not None else left

# checkpointer会自动保存state中的数据到数据库中
class CandidateAgentState(BaseModel):
    messages: Annotated[List[BaseMessage], add_messages]
    candidate: Annotated[CandidateSchema, assign_state_property]
    position: Annotated[PositionSchema, assign_state_property]
    interviewer: Annotated[UserSchema, assign_state_property]


class CandidateProcessAgent:
    def __init__(self,
        candidate: CandidateSchema| None = None,
        position: PositionSchema | None = None,
        interviewer: UserSchema | None = None,
    ):
        self.candidate = candidate
        self.position = position
        self.interviewer = interviewer
        self._checkpointer = None

    async def ainvoke(self, messages: list[BaseMessage], thread_id: str):
        assert self._checkpointer is not None
        agent = create_agent(
            model=qwen_llm,
            system_prompt=CANDIDATE_PROCESS_SYSTEM_PROMPT,
            state_schema=CandidateAgentState,
            middleware=[
                ModelFallbackMiddleware(first_model=deepseek_llm),
                SummarizationMiddleware(
                    model=deepseek_llm,
                    trigger=("tokens", 50000),
                    keep=("tokens", 10000)
                )
            ],
            tools=[],
            checkpointer=self._checkpointer
        )
        response = await agent.invoke({
            "messages": messages,
            "candidate": self.candidate,
        }, {"thread_id": thread_id})
        return response

    async def __aenter__(self):
        self._checkpointer_conn = AsyncPostgresSaver.from_conn_string(settings.DATABASE_AGENT_URL)
        self._checkpointer = await self._checkpointer_conn.__aenter__()
        await self._checkpointer.setup()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self._checkpointer_conn.__aexit__(exc_type, exc_val, exc_tb)


# async with CandidateProcessAgent(candidate, position, interviewer) as agent:
#     await agent.ainvoke()