import pytest

from tasks import candidate_tasks


class FakeCandidateWorkflowService:
    """用于验证 BackgroundTask 层只做委托，不直接编排 Agent。"""

    calls = []

    async def on_candidate_created(self, candidate_id: str):
        self.calls.append(candidate_id)
        return {"result": "ok"}


@pytest.mark.asyncio
async def test_run_candidate_agent_by_id_delegates_to_workflow_service(monkeypatch):
    FakeCandidateWorkflowService.calls = []
    monkeypatch.setattr(
        candidate_tasks,
        "CandidateWorkflowService",
        FakeCandidateWorkflowService,
    )

    result = await candidate_tasks.run_candidate_agent_by_id("candidate-1")

    assert result == {"result": "ok"}
    assert FakeCandidateWorkflowService.calls == ["candidate-1"]
