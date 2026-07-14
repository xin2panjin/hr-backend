from types import SimpleNamespace

import pytest

from iam.permissions import PermissionCode
from iam.services.role_permission_service import (
    RolePermissionService,
    RolePermissionValidationError,
)


class FakeSession:
    def add(self, _):
        pass


@pytest.mark.asyncio
async def test_role_permission_change_requires_reason():
    service = RolePermissionService(FakeSession())
    role = SimpleNamespace(code="ROLE_HR_ADMIN", permissions=[])

    with pytest.raises(RolePermissionValidationError, match="变更原因"):
        await service.replace_permissions(
            role=role,
            permission_ids=[],
            reason=" ",
            actor_id="admin-1",
        )


@pytest.mark.asyncio
async def test_system_admin_must_keep_role_permission_management_capability():
    service = RolePermissionService(FakeSession())

    async def no_permissions(_):
        return []

    service.iam_repo.get_permissions_by_ids = no_permissions
    role = SimpleNamespace(code="ROLE_SYSTEM_ADMIN", permissions=[])

    with pytest.raises(RolePermissionValidationError, match="必须保留"):
        await service.replace_permissions(
            role=role,
            permission_ids=[],
            reason="调整系统管理员权限",
            actor_id="admin-1",
        )


def test_role_permission_management_is_declared_permission_code():
    assert PermissionCode.ROLE_UPDATE_PERMISSIONS.value == "role.update_permissions"
