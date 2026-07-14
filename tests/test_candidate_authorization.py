from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from iam.policies.candidate_policy import CandidatePolicy, CandidateScopeType
from iam.permissions import RoleCode
from models.iam import ScopeTypeEnum
from models.candidate import CandidateStatusEnum
from schemas.candidate_schema import CandidateStatusUpdateSchema
from services.candidate_service import CandidateService


def build_user(
    user_id: str,
    *,
    role_codes: tuple[str, ...] = (),
    managed_department_ids: tuple[str, ...] = (),
):
    return SimpleNamespace(
        id=user_id,
        iam_roles=[
            SimpleNamespace(
                role=SimpleNamespace(code=role_code),
                scopes=[
                    SimpleNamespace(scope_type=ScopeTypeEnum.DEPARTMENT, department_id=department_id)
                    for department_id in managed_department_ids
                ] if role_code == RoleCode.RECRUITER.value else [],
            )
            for role_code in role_codes
        ],
    )


def build_candidate(*, department_id: str = "department-1", position_creator_id: str = "manager-1"):
    return SimpleNamespace(
        id="candidate-1",
        status=CandidateStatusEnum.APPLICATION,
        position=SimpleNamespace(
            id="position-1",
            department_id=department_id,
            creator_id=position_creator_id,
        ),
    )


class FakeCandidateRepo:
    def __init__(self, candidate):
        self.candidate = candidate
        self.status_updates = []

    async def get_by_id(self, candidate_id):
        return self.candidate

    async def update_candidate_status(self, candidate_id, status):
        self.status_updates.append((candidate_id, status))


class FakeSearchProfileService:
    async def rebuild_candidate_profile(self, candidate):
        return None


def test_hr_without_managed_departments_has_no_candidate_scope():
    actor = build_user("hr-1", role_codes=(RoleCode.RECRUITER.value,))

    scope = CandidatePolicy.resolve_scope(actor)

    assert scope.type == CandidateScopeType.NONE
    assert CandidatePolicy.can_read(actor, build_candidate()) is False
    assert CandidatePolicy.build_milvus_filter(
        actor=actor,
        position_id=None,
        status=None,
    ) == 'candidate_id == "__no_candidate_access__"'


def test_hr_can_only_read_candidates_in_managed_departments():
    actor = build_user(
        "hr-1",
        role_codes=(RoleCode.RECRUITER.value,),
        managed_department_ids=("department-1",),
    )

    assert CandidatePolicy.can_read(actor, build_candidate(department_id="department-1"))
    assert not CandidatePolicy.can_read(actor, build_candidate(department_id="department-2"))


def test_regular_user_scope_uses_position_creator_not_candidate_creator():
    actor = build_user("manager-1", role_codes=(RoleCode.HIRING_MANAGER.value,))

    assert CandidatePolicy.can_read(
        actor,
        build_candidate(position_creator_id="manager-1"),
    )
    assert not CandidatePolicy.can_read(
        actor,
        build_candidate(position_creator_id="manager-2"),
    )


@pytest.mark.asyncio
async def test_status_update_rejects_user_outside_candidate_scope():
    candidate_repo = FakeCandidateRepo(build_candidate(position_creator_id="manager-1"))
    service = CandidateService(
        session=None,
        candidate_repo=candidate_repo,
        search_profile_service=FakeSearchProfileService(),
    )

    with pytest.raises(HTTPException) as exc_info:
        await service.update_candidate_status(
            "candidate-1",
            CandidateStatusUpdateSchema(status=CandidateStatusEnum.AI_FILTER_REJECTED),
            build_user("manager-2", role_codes=(RoleCode.HIRING_MANAGER.value,)),
        )

    assert exc_info.value.status_code == 403
    assert candidate_repo.status_updates == []
