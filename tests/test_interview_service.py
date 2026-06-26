from datetime import datetime
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from models.interview import InterviewResultEnum
from schemas.candidate_schema import CandidateStatusUpdateSchema
from models.candidate import CandidateStatusEnum
from services.interview_service import InterviewService


class FakeInterviewRepo:
    def __init__(self, interview=None):
        self.interview = interview
        self.created_interviews = []
        self.updated_interviews = []

    async def create_interview(self, interview_dict):
        self.created_interviews.append(interview_dict)
        return SimpleNamespace(id="interview-created", **interview_dict)

    async def get_by_candidate_id(self, candidate_id):
        return self.interview

    async def update_interview(self, interview_id, interview_dict):
        self.updated_interviews.append((interview_id, interview_dict))
        return SimpleNamespace(id=interview_id, **interview_dict)


def build_user(user_id="interviewer-1"):
    return SimpleNamespace(id=user_id)


@pytest.mark.asyncio
async def test_create_waiting_interview_requires_interview_time():
    service = InterviewService(session=None, interview_repo=FakeInterviewRepo())
    status_data = CandidateStatusUpdateSchema(
        status=CandidateStatusEnum.WAITING_FOR_INTERVIEW,
    )

    with pytest.raises(HTTPException) as exc_info:
        await service.create_waiting_interview("candidate-1", status_data, build_user())

    assert exc_info.value.status_code == 400
    assert "面试时间" in exc_info.value.detail


@pytest.mark.asyncio
async def test_create_waiting_interview_creates_interview():
    interview_repo = FakeInterviewRepo()
    service = InterviewService(session=None, interview_repo=interview_repo)
    interview_time = datetime(2026, 6, 26, 10, 0, 0)
    status_data = CandidateStatusUpdateSchema(
        status=CandidateStatusEnum.WAITING_FOR_INTERVIEW,
        interview_time=interview_time,
    )

    await service.create_waiting_interview("candidate-1", status_data, build_user("interviewer-1"))

    assert interview_repo.created_interviews == [
        {
            "scheduled_time": interview_time,
            "candidate_id": "candidate-1",
            "interviewer_id": "interviewer-1",
        }
    ]


@pytest.mark.asyncio
async def test_mark_interview_rejected_requires_reason():
    service = InterviewService(session=None, interview_repo=FakeInterviewRepo())
    status_data = CandidateStatusUpdateSchema(
        status=CandidateStatusEnum.INTERVIEW_REJECTED,
    )

    with pytest.raises(HTTPException) as exc_info:
        await service.mark_interview_rejected("candidate-1", status_data, build_user())

    assert exc_info.value.status_code == 400
    assert "未通过原因" in exc_info.value.detail


@pytest.mark.asyncio
async def test_mark_interview_rejected_updates_existing_interview_feedback():
    interview_repo = FakeInterviewRepo(interview=SimpleNamespace(id="interview-1"))
    service = InterviewService(session=None, interview_repo=interview_repo)
    status_data = CandidateStatusUpdateSchema(
        status=CandidateStatusEnum.INTERVIEW_REJECTED,
        rejection_reason="技术深度不足",
    )

    await service.mark_interview_rejected("candidate-1", status_data, build_user("interviewer-1"))

    assert interview_repo.updated_interviews == [
        (
            "interview-1",
            {
                "feedback": "技术深度不足",
                "result": InterviewResultEnum.FAILED,
            },
        )
    ]
    assert interview_repo.created_interviews == []


@pytest.mark.asyncio
async def test_mark_interview_rejected_creates_interview_when_missing():
    interview_repo = FakeInterviewRepo(interview=None)
    service = InterviewService(session=None, interview_repo=interview_repo)
    interview_time = datetime(2026, 6, 26, 10, 0, 0)
    status_data = CandidateStatusUpdateSchema(
        status=CandidateStatusEnum.INTERVIEW_REJECTED,
        interview_time=interview_time,
        rejection_reason="技术深度不足",
    )

    await service.mark_interview_rejected("candidate-1", status_data, build_user("interviewer-1"))

    assert interview_repo.created_interviews == [
        {
            "scheduled_time": interview_time,
            "feedback": "技术深度不足",
            "result": InterviewResultEnum.FAILED,
            "candidate_id": "candidate-1",
            "interviewer_id": "interviewer-1",
        }
    ]
    assert interview_repo.updated_interviews == []
