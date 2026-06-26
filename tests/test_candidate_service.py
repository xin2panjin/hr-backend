from datetime import datetime
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from models.candidate import CandidateStatusEnum, GenderEnum
from models.positions import EducationEnum
from models.user import UserStatus
from schemas.candidate_schema import CandidateCreateSchema, CandidateStatusUpdateSchema
from services.candidate_service import CandidateService


class FakeCandidateRepo:
    def __init__(self, candidate=None):
        self.candidate = candidate
        self.created_candidate_info = None
        self.status_updates = []

    async def create_candidate(self, candidate_info):
        self.created_candidate_info = candidate_info
        self.candidate = build_candidate(
            candidate_id="candidate-1",
            status=CandidateStatusEnum.APPLICATION,
        )
        return self.candidate

    async def get_by_id(self, candidate_id):
        return self.candidate

    async def update_candidate_status(self, candidate_id, status):
        self.status_updates.append((candidate_id, status))


class FakeInterviewService:
    def __init__(self):
        self.waiting_calls = []
        self.rejected_calls = []

    async def create_waiting_interview(self, candidate_id, status_data, current_user):
        if not status_data.interview_time:
            raise HTTPException(status_code=400, detail="变更为待面试时必须填写面试时间")
        self.waiting_calls.append((candidate_id, status_data, current_user))

    async def mark_interview_rejected(self, candidate_id, status_data, current_user):
        if not status_data.rejection_reason:
            raise HTTPException(status_code=400, detail="变更为面试未通过时必须填写未通过原因")
        self.rejected_calls.append((candidate_id, status_data, current_user))


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


def build_position(creator):
    return SimpleNamespace(
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
        creator=creator,
        department=creator.department,
        created_at=datetime(2026, 1, 1, 9, 0, 0),
        is_open=True,
    )


def build_candidate(candidate_id, status):
    creator = build_user("creator-1")
    position_creator = build_user("interviewer-1")
    position = build_position(position_creator)
    resume = SimpleNamespace(
        id="resume-1",
        file_path="resume.pdf",
        uploader=creator,
    )
    return SimpleNamespace(
        id=candidate_id,
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
        status=status,
        position=position,
        resume=resume,
        creator=creator,
    )


@pytest.mark.asyncio
async def test_create_candidate_adds_creator_and_returns_candidate_id():
    candidate_repo = FakeCandidateRepo()
    service = CandidateService(
        session=None,
        candidate_repo=candidate_repo,
        interview_service=FakeInterviewService(),
    )
    current_user = build_user("creator-1")
    candidate_data = CandidateCreateSchema(
        name="候选人",
        email="candidate@example.com",
        position_id="position-1",
        resume_id="resume-1",
    )

    candidate_id = await service.create_candidate(candidate_data, current_user)

    assert candidate_repo.created_candidate_info["creator_id"] == "creator-1"
    assert candidate_id == "candidate-1"


@pytest.mark.asyncio
async def test_update_candidate_status_to_waiting_requires_interview_time():
    candidate_repo = FakeCandidateRepo(
        build_candidate("candidate-1", CandidateStatusEnum.AI_FILTER_PASSED)
    )
    service = CandidateService(
        session=None,
        candidate_repo=candidate_repo,
        interview_service=FakeInterviewService(),
    )
    status_data = CandidateStatusUpdateSchema(
        status=CandidateStatusEnum.WAITING_FOR_INTERVIEW,
    )

    with pytest.raises(HTTPException) as exc_info:
        await service.update_candidate_status("candidate-1", status_data, build_user("interviewer-1"))

    assert exc_info.value.status_code == 400
    assert "面试时间" in exc_info.value.detail
    assert candidate_repo.status_updates == []


@pytest.mark.asyncio
async def test_update_candidate_status_to_waiting_creates_interview_and_updates_status():
    candidate_repo = FakeCandidateRepo(
        build_candidate("candidate-1", CandidateStatusEnum.AI_FILTER_PASSED)
    )
    interview_service = FakeInterviewService()
    service = CandidateService(
        session=None,
        candidate_repo=candidate_repo,
        interview_service=interview_service,
    )
    interview_time = datetime(2026, 6, 26, 10, 0, 0)
    status_data = CandidateStatusUpdateSchema(
        status=CandidateStatusEnum.WAITING_FOR_INTERVIEW,
        interview_time=interview_time,
    )

    await service.update_candidate_status("candidate-1", status_data, build_user("interviewer-1"))

    assert len(interview_service.waiting_calls) == 1
    assert interview_service.waiting_calls[0][0] == "candidate-1"
    assert interview_service.waiting_calls[0][1] == status_data
    assert interview_service.waiting_calls[0][2].id == "interviewer-1"
    assert candidate_repo.status_updates == [
        ("candidate-1", CandidateStatusEnum.WAITING_FOR_INTERVIEW)
    ]


@pytest.mark.asyncio
async def test_update_candidate_status_to_rejected_calls_interview_service_and_updates_status():
    candidate_repo = FakeCandidateRepo(
        build_candidate("candidate-1", CandidateStatusEnum.WAITING_FOR_INTERVIEW)
    )
    interview_service = FakeInterviewService()
    service = CandidateService(
        session=None,
        candidate_repo=candidate_repo,
        interview_service=interview_service,
    )
    status_data = CandidateStatusUpdateSchema(
        status=CandidateStatusEnum.INTERVIEW_REJECTED,
        rejection_reason="技术深度不足",
    )

    await service.update_candidate_status("candidate-1", status_data, build_user("interviewer-1"))

    assert len(interview_service.rejected_calls) == 1
    assert interview_service.rejected_calls[0][0] == "candidate-1"
    assert interview_service.rejected_calls[0][1] == status_data
    assert interview_service.rejected_calls[0][2].id == "interviewer-1"
    assert candidate_repo.status_updates == [
        ("candidate-1", CandidateStatusEnum.INTERVIEW_REJECTED)
    ]
