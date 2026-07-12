from models.candidate_agent import CandidateAgentEventModel

from . import BaseRepo


class CandidateAgentEventRepo(BaseRepo):
    async def create_event(self, event_data: dict) -> CandidateAgentEventModel:
        """创建一条候选人 Agent Graph 执行事件。"""
        event = CandidateAgentEventModel(**event_data)
        self.session.add(event)
        await self.session.flush([event])
        return event
