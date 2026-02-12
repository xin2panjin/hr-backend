# langchain：好处就是开发简单，不需要判断一些条件；坏处就是消耗token
# langgraph：好处就是很多逻辑写好了，与大模型的交互次数更少，节省token；坏处逻辑判断稍微复杂一些
import json

from langchain.agents import create_agent
from schemas.candidate_schema import CandidateSchema
from schemas.position_schema import PositionSchema
from schemas.user_schema import UserSchema
from langgraph.graph.message import BaseMessage
from .llms import qwen_llm, deepseek_llm
from .prompts import CANDIDATE_PROCESS_SYSTEM_PROMPT, SCORE_FOR_CANDIDATE_SYSTEM_PROMPT, SCORE_FOR_CANDIDATE_USER_PROMPT
from langchain.agents.middleware import ModelFallbackMiddleware, SummarizationMiddleware
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from settings import settings
from pydantic import BaseModel
from typing import Annotated, List, TypeVar, Optional
from langgraph.graph.message import add_messages
from langchain.tools import tool, ToolRuntime
from schemas.agent_schema import AgentCandidateScoreSchema
from langchain_core.prompts import PromptTemplate
from models import AsyncSession, AsyncSessionFactory
from repository.candidate_repo import CandidateAIScoreRepo, CandidateRepo
from models.candidate import CandidateStatusEnum
from repository.user_repo import UserRepo
from models.user import DingdingUserModel
from core.dingtalk import DingTalkHttp
from core.cache import HRCache
from loguru import logger
from core.cache import DingTalkTokenInfoSchema
from datetime import datetime, timedelta
from typing import Any
from utils.available_time import find_available_slot
from utils.iso8601 import datetime_to_iso8601_beijing, iso8601_to_datetime_beijing


async def get_dingtalk_access_token(user_id: str) -> str:
    dingding_http = DingTalkHttp()

    # 2. 从缓存中获取该用户的refresh_token
    cache: HRCache = HRCache()
    token_info = await cache.get_dingtalk_info(user_id)
    if not token_info:
        error_message = f"{user_id}用户钉钉授权已过期！"
        logger.error(error_message)
        raise ValueError(error_message)

    try:
        # 3. 根据refresh_token刷新access_token
        refresh_token, access_token = await dingding_http.refresh_access_token(token_info.refresh_token)

        # 4. 将获取到的token信息重新设置到缓存中
        await cache.set_dingtalk_info(
            DingTalkTokenInfoSchema(
                user_id=user_id,
                access_token=access_token,
                refresh_token=refresh_token
            )
        )

        return access_token
    except Exception as e:
        logger.error(e)
        raise ValueError(e)


T = TypeVar("T")

def assign_state_property(left: T, right: Optional[T]) -> T:
    return right if right is not None else left

# checkpointer会自动保存state中的数据到数据库中
class CandidateAgentState(BaseModel):
    messages: Annotated[List[BaseMessage], add_messages]
    candidate: Annotated[CandidateSchema, assign_state_property]
    position: Annotated[PositionSchema, assign_state_property]
    interviewer: Annotated[UserSchema, assign_state_property]

@tool
async def score_for_candidate(
    runtime: ToolRuntime[CandidateAgentState]
):
    """
    根据职位信息，给职位上的候选人进行评分。
    评分结果会存入数据库中，并根据评分结果修改候选人状态。
    return：
    - str | None: 评分结果的JSON字符串，如果评分失败则返回None
    """
    candidate: CandidateSchema = runtime.state['candidate']
    position: PositionSchema = runtime.state['position']

    score_agent = create_agent(
        model=qwen_llm,
        system_prompt=SCORE_FOR_CANDIDATE_SYSTEM_PROMPT,
        middleware=[ModelFallbackMiddleware(first_model=deepseek_llm)],
        response_format=AgentCandidateScoreSchema
    )
    user_prompt_template = PromptTemplate.from_template(SCORE_FOR_CANDIDATE_USER_PROMPT)
    user_prompt = user_prompt_template.invoke({
        "candidate": candidate.model_dump_json(),
        "position": position.model_dump_json()
    })
    response = score_agent.ainvoke({
        "messages": [{
            "role": "user",
            "content": user_prompt
        }]
    })
    candiate_score: AgentCandidateScoreSchema = response['structured_response']
    # 将得分情况存储到数据库中
    async with AsyncSessionFactory() as session:
        async with session.begin():
            try:
                score_repo = CandidateAIScoreRepo(session)
                candidate_repo = CandidateRepo(session)
                # 1. 将得分插入到数据库中
                await score_repo.create_candidate_score(
                    candidate_id=candidate.id,
                    candidate_score_dict=candiate_score.model_dump()
                )
                # 2. 判断得分情况，如果超过8分，那么修改状态为AI_PASS，否则就是AI_FAILED
                status = CandidateStatusEnum.AI_FILTER_FAILED
                if candiate_score.overall_score > 8:
                    status = CandidateStatusEnum.AI_FILTER_PASSED

                await candidate_repo.update_candidate_status(candidate_id=candidate.id, status=status)
            except Exception as e:
                return f"得分工具执行失败，错误信息为：{e}"
    return f"得分工具执行成功！该候选人得分为：{candiate_score.model_dump_json()}"

@tool
async def get_interviewer_available_slot(
    runtime: ToolRuntime[CandidateAgentState]
):
    """
    根据职位信息，获取面试官可用的面试时间。
    """
    interviewer: UserSchema = runtime.state['interviewer']
    # 1. 获取该用户的钉钉账号
    union_id: str|None = None
    async with AsyncSessionFactory() as session:
        async with session.begin():
            try:
                user_repo = UserRepo(session)
                dingding_user: DingdingUserModel = user_repo.get_dingding_user(user_id=interviewer.user_id)
                if not dingding_user:
                    return f"获取候选人可用时间失败，没有绑定钉钉账号！"
                union_id = dingding_user.union_id
            except Exception as e:
                return f"获取候选人可用时间失败：{e}"

    try:
        # 2. 获取access_token
        access_token: str = await get_dingtalk_access_token(interviewer.user_id)
    except Exception as e:
        logger.error(e)
        return f"获取面试官可用时间失败：{e}"

    # 3. 从钉钉上获取面试官的日程安排
    try:
        dingtalk_http = DingTalkHttp()
        now = datetime.now()
        tomorrow_nine = datetime(year=now.year, month=now.month, day=now.day, hour=9)
        events: list[dict[str, Any]] = await dingtalk_http.get_calendar_list(
            union_id=union_id,
            access_token=access_token,
            time_min=tomorrow_nine,
            time_max=tomorrow_nine + timedelta(days=7),
        )
        busy_slots = [
            (iso8601_to_datetime_beijing(event['start']['dateTime']), iso8601_to_datetime_beijing(event['end']['dateTime']))
            for event in events
        ]
        available_slots: list[tuple[datetime, datetime]] = find_available_slot(
            busy_slots,
            start_date=tomorrow_nine
        )
        if len(available_slots) == 0:
            return f"获取面试官可用时间失败：7天内没有空闲时间！"
        available_times = [(iso8601_to_datetime_beijing(slot[0]), iso8601_to_datetime_beijing(slot[1])) for slot in available_slots]
        return f"找到面试官可用的时间：{json.dumps(available_times)}"
    except Exception as e:
        return f"获取面试官可用时间失败：{e}"


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
            tools=[
                score_for_candidate,
                get_interviewer_available_slot
            ],
            checkpointer=self._checkpointer
        )
        response = await agent.invoke({
            "messages": messages,
            "candidate": self.candidate,
            "position": self.position,
            "interviewer": self.interviewer,
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