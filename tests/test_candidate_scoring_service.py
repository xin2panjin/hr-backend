import pytest

from models.candidate import CandidateStatusEnum
from schemas.agent_schema import AgentCandidateScoreSchema
from services import candidate_scoring_service as scoring_module
from services.candidate_scoring_service import CandidateScoringService


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


class FakeScoreRepo:
    created = []

    def __init__(self, session):
        self.session = session

    async def create_candidate_score(self, candidate_id, candidate_score_dict):
        self.created.append((candidate_id, candidate_score_dict))


class FakeCandidateRepo:
    status_updates = []

    def __init__(self, session):
        self.session = session

    async def update_candidate_status(self, candidate_id, status):
        self.status_updates.append((candidate_id, status))


def build_score(overall_score: int) -> AgentCandidateScoreSchema:
    return AgentCandidateScoreSchema(
        work_experience_score=8,
        technical_skills_score=9,
        soft_skills_score=8,
        educational_background_score=8,
        project_experience_score=9,
        overall_score=overall_score,
        summary="匹配",
        strengths=["技术能力"],
        weaknesses=["信息有限"],
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("overall_score", "expected_status"),
    [
        (9, CandidateStatusEnum.AI_FILTER_PASSED),
        (8, CandidateStatusEnum.AI_FILTER_REJECTED),
    ],
)
async def test_save_score_persists_score_and_status(
    monkeypatch,
    overall_score,
    expected_status,
):
    FakeScoreRepo.created = []
    FakeCandidateRepo.status_updates = []
    monkeypatch.setattr(scoring_module, "AsyncSessionFactory", FakeSessionFactory)
    monkeypatch.setattr(scoring_module, "CandidateAIScoreRepo", FakeScoreRepo)
    monkeypatch.setattr(scoring_module, "CandidateRepo", FakeCandidateRepo)

    status = await CandidateScoringService().save_score(
        "candidate-1",
        build_score(overall_score),
    )

    assert status == expected_status
    assert FakeScoreRepo.created[0][0] == "candidate-1"
    assert FakeScoreRepo.created[0][1]["overall_score"] == overall_score
    assert FakeCandidateRepo.status_updates == [("candidate-1", expected_status)]
