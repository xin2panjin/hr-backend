from typing import Sequence

from langchain_core.messages import BaseMessage

from agents.candidate.agent import CandidateProcessAgent
from models import AsyncSessionFactory
from repository.candidate_repo import CandidateRepo
from schemas.candidate_schema import CandidateSchema
from schemas.position_schema import PositionSchema
from schemas.user_schema import UserSchema


class CandidateWorkflowService:
    """候选人 Agent 流程的应用服务入口。

    Router、BackgroundTask、Scheduler 只负责把外部事件转成方法调用；
    这里统一完成候选人上下文加载、thread_id 生成和 Agent 调用。
    """

    @staticmethod
    def build_thread_id(candidate_id: str, position_id: str) -> str:
        """生成候选人流程的稳定会话 ID，避免用邮箱串起多个职位的历史流程。"""
        return f"candidate-process:{candidate_id}:{position_id}"

    async def on_candidate_created(self, candidate_id: str):
        """候选人创建后触发 AI 评分和后续邀约流程。"""
        candidate, position, interviewer = await self._load_context_by_candidate_id(
            candidate_id
        )
        return await self.run_candidate_agent(
            candidate=candidate,
            position=position,
            interviewer=interviewer,
            messages=[
                {
                    "role": "user",
                    "content": (
                        f"候选人信息：{candidate.model_dump_json()}，"
                        f"职位信息：{position.model_dump_json()}"
                    ),
                }
            ],
        )

    async def on_candidate_email_received(self, from_email: str, content: str):
        """候选人邮件回复后触发流程继续执行。"""
        candidate, position, interviewer = await self._load_context_by_candidate_email(
            from_email
        )
        return await self.run_candidate_agent(
            candidate=candidate,
            position=position,
            interviewer=interviewer,
            messages=[
                {
                    "role": "user",
                    "content": f"收到邮件内容：{content}",
                }
            ],
        )

    async def run_candidate_agent(
        self,
        *,
        candidate: CandidateSchema,
        position: PositionSchema,
        interviewer: UserSchema,
        messages: Sequence[BaseMessage | dict],
    ):
        """以统一 thread_id 调用候选人 Agent，供不同入口复用。"""
        thread_id = self.build_thread_id(candidate.id, position.id)
        async with CandidateProcessAgent(
            candidate=candidate,
            position=position,
            interviewer=interviewer,
        ) as agent:
            return await agent.ainvoke(
                messages=list(messages),
                thread_id=thread_id,
            )

    async def _load_context_by_candidate_id(
        self,
        candidate_id: str,
    ) -> tuple[CandidateSchema, PositionSchema, UserSchema]:
        """按候选人 ID 加载 Agent 运行所需的候选人、职位和面试官信息。"""
        async with AsyncSessionFactory() as session:
            async with session.begin():
                candidate_model = await CandidateRepo(session).get_by_id(candidate_id)
                if not candidate_model:
                    raise ValueError(f"候选人不存在：{candidate_id}")
                return self._build_context(candidate_model)

    async def _load_context_by_candidate_email(
        self,
        email: str,
    ) -> tuple[CandidateSchema, PositionSchema, UserSchema]:
        """按候选人邮箱加载最近一次投递的流程上下文。"""
        async with AsyncSessionFactory() as session:
            async with session.begin():
                candidate_model = await CandidateRepo(session).get_latest_by_email(email)
                if not candidate_model:
                    raise ValueError(f"未找到邮箱对应的候选人：{email}")
                return self._build_context(candidate_model)

    @staticmethod
    def _build_context(candidate_model) -> tuple[CandidateSchema, PositionSchema, UserSchema]:
        """将 ORM 对象转成 Agent 状态中使用的 Pydantic Schema。"""
        candidate = CandidateSchema.model_validate(candidate_model)
        position = PositionSchema.model_validate(candidate_model.position)
        interviewer = UserSchema.model_validate(candidate_model.position.creator)
        return candidate, position, interviewer
