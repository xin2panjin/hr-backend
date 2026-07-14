from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from iam.policies.position_policy import PositionPolicy, PositionScopeType
from iam.permissions import RoleCode
from models.iam import ScopeTypeEnum


def build_user(
    user_id: str,
    *,
    department_id: str = "department-1",
    role_codes: tuple[str, ...] = (),
    managed_department_ids: tuple[str, ...] = (),
):
    return SimpleNamespace(
        id=user_id,
        department_id=department_id,
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


def build_position(*, department_id: str = "department-1", creator_id: str = "manager-1"):
    return SimpleNamespace(department_id=department_id, creator_id=creator_id)


def test_hr_without_managed_departments_has_no_position_scope():
    actor = build_user("hr-1", role_codes=(RoleCode.RECRUITER.value,))

    assert PositionPolicy.resolve_scope(actor).type == PositionScopeType.NONE
    assert not PositionPolicy.can_read(actor, build_position())


def test_normal_user_can_only_manage_own_positions():
    actor = build_user("manager-1", role_codes=(RoleCode.HIRING_MANAGER.value,))

    assert PositionPolicy.can_read(actor, build_position(creator_id="manager-1"))
    assert not PositionPolicy.can_read(actor, build_position(creator_id="manager-2"))


def test_hr_can_manage_positions_in_managed_departments():
    actor = build_user(
        "hr-1",
        role_codes=(RoleCode.RECRUITER.value,),
        managed_department_ids=("department-2",),
    )

    assert PositionPolicy.can_read(actor, build_position(department_id="department-2"))
    assert not PositionPolicy.can_read(actor, build_position(department_id="department-1"))


def test_normal_user_cannot_delete_colleague_position():
    actor = build_user("manager-1", role_codes=(RoleCode.HIRING_MANAGER.value,))

    with pytest.raises(HTTPException) as exc_info:
        PositionPolicy.ensure_can_delete(actor, build_position(creator_id="manager-2"))

    assert exc_info.value.status_code == 403
