from datetime import datetime
from types import SimpleNamespace

import pytest

from iam.services.organization_service import (
    DepartmentArchiveConflict,
    OrganizationService,
    OrganizationValidationError,
)
from models.user import DepartmentStatus, UserStatus


class FakeSession:
    def __init__(self):
        self.added = []

    def add(self, item):
        self.added.append(item)

    async def execute(self, _):
        return SimpleNamespace(rowcount=0)


class FakeDepartmentRepo:
    def __init__(self, departments=(), dependencies=None):
        self.departments = {department.id: department for department in departments}
        self.dependencies = dependencies or {
            "active_users": 0,
            "open_positions": 0,
            "active_role_scopes": 0,
            "active_child_departments": 0,
            "legacy_managed_department_bindings": 0,
            "pending_invitations": 0,
        }

    async def get_by_id(self, department_id):
        return self.departments.get(department_id)

    async def get_by_code(self, _):
        return None

    async def get_by_name(self, _):
        return None

    async def get_archive_dependencies(self, _):
        return self.dependencies


def make_service(department_repo):
    service = OrganizationService(FakeSession())
    service.department_repo = department_repo
    return service


@pytest.mark.asyncio
async def test_archive_department_rejects_all_effective_scope_dependencies():
    department = SimpleNamespace(
        id="dept-1",
        code="DEPT-ENGINEERING-001",
        name="工程部",
        description=None,
        status=DepartmentStatus.ACTIVE,
        parent_id=None,
    )
    service = make_service(
        FakeDepartmentRepo(
            [department],
            {
                "active_users": 0,
                "open_positions": 0,
                "active_role_scopes": 0,
                "active_child_departments": 0,
                "legacy_managed_department_bindings": 1,
                "pending_invitations": 0,
            },
        )
    )

    with pytest.raises(DepartmentArchiveConflict) as exc_info:
        await service.archive_department(department=department, actor_id="admin-1")

    assert exc_info.value.dependencies["legacy_managed_department_bindings"] == 1
    assert department.status == DepartmentStatus.ACTIVE


@pytest.mark.asyncio
async def test_department_parent_cannot_create_cycle():
    current = SimpleNamespace(
        id="dept-current",
        parent_id="dept-child",
        status=DepartmentStatus.ACTIVE,
    )
    child = SimpleNamespace(
        id="dept-child",
        parent_id="dept-current",
        status=DepartmentStatus.ACTIVE,
    )
    service = make_service(FakeDepartmentRepo([current, child]))

    with pytest.raises(OrganizationValidationError, match="子孙"):
        await service._validate_parent(
            parent_id="dept-child",
            current_department_id="dept-current",
        )


@pytest.mark.asyncio
async def test_resigning_user_increments_version_and_revokes_roles():
    user = SimpleNamespace(
        id="user-1",
        realname="测试用户",
        phone_number=None,
        department_id="dept-1",
        status=UserStatus.ACTIVE,
        authz_version=3,
        is_superuser=False,
        disabled_at=None,
        disabled_by=None,
    )
    role = SimpleNamespace(revoked_at=None, revoke_reason=None)
    service = make_service(FakeDepartmentRepo())

    async def get_active_roles(_):
        return [role]

    service._get_active_user_roles = get_active_roles
    result = await service.update_user_status(
        user=user,
        user_status=UserStatus.RESIGNED,
        actor_id="admin-1",
    )

    assert result.status == UserStatus.RESIGNED
    assert result.authz_version == 4
    assert result.disabled_by == "admin-1"
    assert isinstance(result.disabled_at, datetime)
    assert isinstance(role.revoked_at, datetime)
    assert role.revoke_reason == "用户离职"
    assert service.session.added[-1].action == "user.status.update"
