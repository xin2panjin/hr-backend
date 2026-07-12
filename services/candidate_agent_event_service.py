from models import AsyncSessionFactory
from repository.candidate_agent_repo import CandidateAgentEventRepo


class CandidateAgentEventService:
    """候选人 Agent Graph 业务审计事件写入服务。"""

    async def record_event(self, event_data: dict) -> None:
        """独立事务写入 Graph 执行事件，避免影响主业务事务。"""
        async with AsyncSessionFactory() as session:
            async with session.begin():
                await CandidateAgentEventRepo(session).create_event(event_data)
