from datetime import datetime
from types import SimpleNamespace

import pytest

from agents.candidate.nodes import context as context_module
from agents.candidate.nodes.context import (
    get_state_value,
    load_candidate_runtime_context,
)
from agents.candidate.state import CandidateAgentState
from models.candidate import CandidateStatusEnum, GenderEnum
from models.positions import EducationEnum
from models.user import UserStatus


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


def build_candidate_model():
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


def test_get_state_value_supports_dict_and_pydantic_state():
    assert get_state_value({"candidate_id": "candidate-1"}, "candidate_id") == (
        "candidate-1"
    )

    state = CandidateAgentState(candidate_id="candidate-2")
    assert get_state_value(state, "candidate_id") == "candidate-2"


@pytest.mark.asyncio
async def test_load_candidate_runtime_context_loads_schema_by_ids(monkeypatch):
    FakeCandidateRepo.candidate = build_candidate_model()
    monkeypatch.setattr(
        context_module,
        "AsyncSessionFactory",
        lambda: FakeSessionFactory(),
    )
    monkeypatch.setattr(context_module, "CandidateRepo", FakeCandidateRepo)

    context = await load_candidate_runtime_context(
        {
            "candidate_id": "candidate-1",
            "position_id": "position-1",
            "interviewer_id": "interviewer-1",
        }
    )

    assert context.candidate.id == "candidate-1"
    assert context.position.id == "position-1"
    assert context.interviewer.id == "interviewer-1"


@pytest.mark.asyncio
async def test_load_candidate_runtime_context_rejects_position_mismatch(monkeypatch):
    FakeCandidateRepo.candidate = build_candidate_model()
    monkeypatch.setattr(
        context_module,
        "AsyncSessionFactory",
        lambda: FakeSessionFactory(),
    )
    monkeypatch.setattr(context_module, "CandidateRepo", FakeCandidateRepo)

    with pytest.raises(ValueError) as exc_info:
        await load_candidate_runtime_context(
            {
                "candidate_id": "candidate-1",
                "position_id": "other-position",
                "interviewer_id": "interviewer-1",
            }
        )

    assert "候选人职位与流程状态不一致" in str(exc_info.value)
