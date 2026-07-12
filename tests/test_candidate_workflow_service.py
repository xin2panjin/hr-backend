from datetime import datetime
from types import SimpleNamespace

import pytest

from models.candidate import CandidateStatusEnum, GenderEnum
from models.positions import EducationEnum
from models.user import UserStatus
from schemas.candidate_schema import CandidateSchema
from schemas.position_schema import PositionSchema
from schemas.user_schema import UserSchema
from agents.candidate.state import CandidateEventType
from services import candidate_workflow_service as workflow_module
from services.candidate_workflow_service import CandidateWorkflowService


class FakeCandidateProcessAgent:
    """记录 Agent 调用参数，避免单测真实访问 LLM 和 checkpoint 数据库。"""

    calls = []

    def __init__(self):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def ainvoke(self, state, thread_id):
        self.calls.append(
            {
                "state": state,
                "thread_id": thread_id,
            }
        )
        return {"thread_id": thread_id}


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

    async def get_latest_by_email(self, email):
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


def build_schemas():
    candidate_model = build_candidate_model()
    return (
        CandidateSchema.model_validate(candidate_model),
        PositionSchema.model_validate(candidate_model.position),
        UserSchema.model_validate(candidate_model.position.creator),
    )


def test_build_thread_id_uses_candidate_and_position_id():
    assert (
        CandidateWorkflowService.build_thread_id("candidate-1", "position-1")
        == "candidate-process:candidate-1:position-1"
    )


@pytest.mark.asyncio
async def test_run_candidate_agent_uses_stable_candidate_process_thread_id(monkeypatch):
    FakeCandidateProcessAgent.calls = []
    monkeypatch.setattr(
        workflow_module,
        "CandidateProcessAgent",
        FakeCandidateProcessAgent,
    )
    candidate, position, interviewer = build_schemas()

    result = await CandidateWorkflowService().run_candidate_agent(
        candidate=candidate,
        position=position,
        interviewer=interviewer,
        messages=[{"role": "user", "content": "开始处理候选人"}],
    )

    assert result == {"thread_id": "candidate-process:candidate-1:position-1"}
    assert FakeCandidateProcessAgent.calls[0]["thread_id"] == (
        "candidate-process:candidate-1:position-1"
    )
    state = FakeCandidateProcessAgent.calls[0]["state"]
    assert state["candidate_id"] == "candidate-1"
    assert state["position_id"] == "position-1"
    assert state["interviewer_id"] == "interviewer-1"
    assert state["event_type"] == CandidateEventType.CANDIDATE_CREATED
    assert "candidate" not in state
    assert "position" not in state
    assert "interviewer" not in state


@pytest.mark.asyncio
async def test_on_candidate_created_loads_context_and_invokes_agent(monkeypatch):
    FakeCandidateRepo.candidate = build_candidate_model()
    FakeCandidateProcessAgent.calls = []
    monkeypatch.setattr(
        workflow_module,
        "AsyncSessionFactory",
        lambda: FakeSessionFactory(),
    )
    monkeypatch.setattr(workflow_module, "CandidateRepo", FakeCandidateRepo)
    monkeypatch.setattr(
        workflow_module,
        "CandidateProcessAgent",
        FakeCandidateProcessAgent,
    )

    result = await CandidateWorkflowService().on_candidate_created("candidate-1")

    assert result == {"thread_id": "candidate-process:candidate-1:position-1"}
    state = FakeCandidateProcessAgent.calls[0]["state"]
    assert state["candidate_id"] == "candidate-1"
    assert state["position_id"] == "position-1"
    assert state["interviewer_id"] == "interviewer-1"
    assert state["event_type"] == CandidateEventType.CANDIDATE_CREATED
    assert "候选人信息" not in state["messages"][0]["content"]


@pytest.mark.asyncio
async def test_on_candidate_email_received_uses_email_event_type(monkeypatch):
    FakeCandidateRepo.candidate = build_candidate_model()
    FakeCandidateProcessAgent.calls = []
    monkeypatch.setattr(
        workflow_module,
        "AsyncSessionFactory",
        lambda: FakeSessionFactory(),
    )
    monkeypatch.setattr(workflow_module, "CandidateRepo", FakeCandidateRepo)
    monkeypatch.setattr(
        workflow_module,
        "CandidateProcessAgent",
        FakeCandidateProcessAgent,
    )

    result = await CandidateWorkflowService().on_candidate_email_received(
        from_email="Candidate@Example.com",
        content="我周二上午 10 点可以参加面试",
    )

    assert result == {"thread_id": "candidate-process:candidate-1:position-1"}
    state = FakeCandidateProcessAgent.calls[0]["state"]
    assert state["candidate_id"] == "candidate-1"
    assert state["position_id"] == "position-1"
    assert state["interviewer_id"] == "interviewer-1"
    assert state["event_type"] == CandidateEventType.CANDIDATE_EMAIL_RECEIVED
    assert "我周二上午 10 点可以参加面试" in state["messages"][0]["content"]
    assert "candidate" not in state
    assert "position" not in state
    assert "interviewer" not in state


@pytest.mark.asyncio
async def test_on_candidate_created_raises_when_candidate_missing(monkeypatch):
    FakeCandidateRepo.candidate = None
    monkeypatch.setattr(
        workflow_module,
        "AsyncSessionFactory",
        lambda: FakeSessionFactory(),
    )
    monkeypatch.setattr(workflow_module, "CandidateRepo", FakeCandidateRepo)

    with pytest.raises(ValueError) as exc_info:
        await CandidateWorkflowService().on_candidate_created("missing-candidate")

    assert "候选人不存在" in str(exc_info.value)
