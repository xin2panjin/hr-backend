from datetime import datetime
from types import SimpleNamespace

import pytest

from models.candidate import CandidateStatusEnum, GenderEnum
from models.positions import EducationEnum
from models.user import UserStatus
from tasks import candidate_tasks


class FakeSessionContext:
    async def __aenter__(self):
        return SimpleNamespace()

    async def __aexit__(self, exc_type, exc, tb):
        return None


class FakeSessionFactory:
    async def __aenter__(self):
        return SimpleNamespace(begin=lambda: FakeSessionContext())

    async def __aexit__(self, exc_type, exc, tb):
        return None


class FakeCandidateRepo:
    candidate = None

    def __init__(self, session):
        self.session = session

    async def get_by_id(self, candidate_id):
        return self.candidate


def build_user(user_id="user-1"):
    department = SimpleNamespace(
        id="department-1",
        name="研发部",
        description=None,
    )
    return SimpleNamespace(
        id=user_id,
        username=f"{user_id}-name",
        email=f"{user_id}@example.com",
        phone_number=None,
        realname="测试用户",
        avatar=None,
        department=department,
        status=UserStatus.ACTIVE,
        is_superuser=False,
        is_hr=False,
        created_at=datetime(2026, 1, 1, 9, 0, 0),
    )


def build_candidate():
    creator = build_user("creator-1")
    interviewer = build_user("interviewer-1")
    position = SimpleNamespace(
        id="position-1",
        title="Python 工程师",
        description="负责后端开发",
        requirements="熟悉 FastAPI",
        min_salary=10000,
        max_salary=20000,
        deadline=None,
        recruitment_count=1,
        education=EducationEnum.BACHELOR,
        work_year=1,
        creator=interviewer,
        department=interviewer.department,
        created_at=datetime(2026, 1, 1, 9, 0, 0),
        is_open=True,
    )
    resume = SimpleNamespace(
        id="resume-1",
        file_path="resume.pdf",
        uploader=creator,
    )
    return SimpleNamespace(
        id="candidate-1",
        name="候选人",
        email="candidate@example.com",
        gender=GenderEnum.UNKNOWN,
        birthday=None,
        phone_number=None,
        work_experience=None,
        project_experience=None,
        education_experience=None,
        self_evaluation=None,
        other_information=None,
        skills=None,
        status=CandidateStatusEnum.APPLICATION,
        position=position,
        resume=resume,
        creator=creator,
    )


@pytest.mark.asyncio
async def test_run_candidate_agent_by_id_loads_candidate_and_invokes_agent(monkeypatch):
    FakeCandidateRepo.candidate = build_candidate()
    calls = []

    async def fake_run_candidate_agent(candidate, position, interviewer):
        calls.append((candidate, position, interviewer))
        return {"result": "ok"}

    monkeypatch.setattr(candidate_tasks, "AsyncSessionFactory", lambda: FakeSessionFactory())
    monkeypatch.setattr(candidate_tasks, "CandidateRepo", FakeCandidateRepo)
    monkeypatch.setattr(candidate_tasks, "run_candidate_agent", fake_run_candidate_agent)

    result = await candidate_tasks.run_candidate_agent_by_id("candidate-1")

    assert result == {"result": "ok"}
    assert len(calls) == 1
    assert calls[0][0].id == "candidate-1"
    assert calls[0][1].id == "position-1"
    assert calls[0][2].id == "interviewer-1"


@pytest.mark.asyncio
async def test_run_candidate_agent_by_id_raises_when_candidate_missing(monkeypatch):
    FakeCandidateRepo.candidate = None

    monkeypatch.setattr(candidate_tasks, "AsyncSessionFactory", lambda: FakeSessionFactory())
    monkeypatch.setattr(candidate_tasks, "CandidateRepo", FakeCandidateRepo)

    with pytest.raises(ValueError) as exc_info:
        await candidate_tasks.run_candidate_agent_by_id("missing-candidate")

    assert "候选人不存在" in str(exc_info.value)
