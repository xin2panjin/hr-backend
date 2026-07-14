from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from iam.services.role_assignment_service import (
    RoleAssignmentConflict,
    RoleAssignmentService,
    RoleAssignmentValidationError,
)
from models.user import DepartmentStatus, UserStatus


class FakeSession:
    def __init__(self):
        self.added = []

    def add(self, item):
        self.added.append(item)

    async def flush(self):
        for item in self.added:
            if getattr(item, "id", None) is None:
                item.id = "generated-user-role-id"


class FakeIamRepo:
    def __init__(self, role, existing=None):
        self.role = role
        self.existing = existing

    async def get_role_by_code(self, role_code):
        return self.role if role_code == self.role.code else None

    async def get_unrevoked_user_role(self, **_):
        return self.existing


class FakeDepartmentRepo:
    def __init__(self, departments):
        self.departments = departments

    async def get_by_id(self, department_id):
        return self.departments.get(department_id)


def build_service(*, role_code="ROLE_HR_RECRUITER", existing=None, departments=None):
    service = RoleAssignmentService(FakeSession())
    service.iam_repo = FakeIamRepo(
        SimpleNamespace(id=f"role-{role_code}", code=role_code),
        existing=existing,
    )
    service.department_repo = FakeDepartmentRepo(departments or {})
    return service


def build_user():
    return SimpleNamespace(id="user-1", status=UserStatus.ACTIVE, authz_version=7)


@pytest.mark.asyncio
async def test_recruiter_grant_requires_at_least_one_department_scope():
    service = build_service()

    with pytest.raises(RoleAssignmentValidationError, match="至少一个"):
        await service.grant_role(
            user=build_user(),
            role_code="ROLE_HR_RECRUITER",
            department_ids=[],
            expires_at=None,
            reason=None,
            actor_id="admin-1",
        )


@pytest.mark.asyncio
async def test_grant_recruiter_normalizes_scopes_and_bumps_authz_version():
    department = SimpleNamespace(id="dept-1", status=DepartmentStatus.ACTIVE)
    service = build_service(departments={"dept-1": department})
    user = build_user()

    user_role = await service.grant_role(
        user=user,
        role_code="ROLE_HR_RECRUITER",
        department_ids=["dept-1", "dept-1"],
        expires_at=datetime.now() + timedelta(days=7),
        reason="负责研发部门招聘",
        actor_id="admin-1",
    )

    assert user.authz_version == 8
    assert user_role.role.code == "ROLE_HR_RECRUITER"
    assert [scope.department_id for scope in user_role.scopes] == ["dept-1"]
    assert service.session.added[-1].action == "user_role.grant"


@pytest.mark.asyncio
async def test_active_role_cannot_be_granted_twice():
    role = SimpleNamespace(code="ROLE_EMPLOYEE")
    existing = SimpleNamespace(
        id="user-role-1",
        expires_at=None,
        revoked_at=None,
        role=role,
        scopes=[],
    )
    service = build_service(role_code="ROLE_EMPLOYEE", existing=existing)

    with pytest.raises(RoleAssignmentConflict, match="已拥有"):
        await service.grant_role(
            user=build_user(),
            role_code="ROLE_EMPLOYEE",
            department_ids=[],
            expires_at=None,
            reason=None,
            actor_id="admin-1",
        )


@pytest.mark.asyncio
async def test_scope_replace_rejects_non_recruiter_role():
    user_role = SimpleNamespace(
        id="user-role-1",
        role=SimpleNamespace(code="ROLE_HIRING_MANAGER"),
        revoked_at=None,
        expires_at=None,
        scopes=[],
    )
    service = build_service(role_code="ROLE_HIRING_MANAGER")

    with pytest.raises(RoleAssignmentValidationError, match="不支持"):
        await service.replace_department_scopes(
            user_role=user_role,
            user=build_user(),
            department_ids=["dept-1"],
            actor_id="admin-1",
            reason=None,
        )


@pytest.mark.asyncio
async def test_revoke_role_requires_reason_and_bumps_authz_version():
    user_role = SimpleNamespace(
        id="user-role-1",
        role=SimpleNamespace(code="ROLE_EMPLOYEE"),
        revoked_at=None,
        revoke_reason=None,
        expires_at=None,
        scopes=[],
    )
    service = build_service(role_code="ROLE_EMPLOYEE")
    user = build_user()

    result = await service.revoke_role(
        user_role=user_role,
        user=user,
        actor_id="admin-1",
        reason="权限调整",
    )

    assert result.revoke_reason == "权限调整"
    assert result.revoked_at is not None
    assert user.authz_version == 8
    assert service.session.added[-1].action == "user_role.revoke"
