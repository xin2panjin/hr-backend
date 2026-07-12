from types import SimpleNamespace

import pytest

from services import candidate_agent_event_service as event_module
from services.candidate_agent_event_service import CandidateAgentEventService


class FakeTransaction:
    async def __aenter__(self):
        return None

    async def __aexit__(self, exc_type, exc, tb):
        return None


class FakeSession:
    def begin(self):
        return FakeTransaction()


class FakeSessionFactory:
    async def __aenter__(self):
        return FakeSession()

    async def __aexit__(self, exc_type, exc, tb):
        return None


class FakeCandidateAgentEventRepo:
    created = []

    def __init__(self, session):
        self.session = session

    async def create_event(self, event_data):
        self.created.append(event_data)
        return SimpleNamespace(id="event-1", **event_data)


@pytest.mark.asyncio
async def test_record_event_creates_candidate_agent_event(monkeypatch):
    FakeCandidateAgentEventRepo.created = []
    monkeypatch.setattr(event_module, "AsyncSessionFactory", FakeSessionFactory)
    monkeypatch.setattr(
        event_module,
        "CandidateAgentEventRepo",
        FakeCandidateAgentEventRepo,
    )

    await CandidateAgentEventService().record_event(
        {
            "thread_id": "candidate-process:candidate-1:position-1",
            "candidate_id": "candidate-1",
            "position_id": "position-1",
            "node_name": "send_invitation",
            "action_type": "node_exit",
            "status": "succeeded",
        }
    )

    assert FakeCandidateAgentEventRepo.created == [
        {
            "thread_id": "candidate-process:candidate-1:position-1",
            "candidate_id": "candidate-1",
            "position_id": "position-1",
            "node_name": "send_invitation",
            "action_type": "node_exit",
            "status": "succeeded",
        }
    ]
