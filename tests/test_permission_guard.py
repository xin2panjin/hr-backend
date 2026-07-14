from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from dependencies import require_permission
from iam.permissions import PermissionCode


class FakeSession:
    def __init__(self, roles):
        self.roles = roles

    @asynccontextmanager
    async def begin(self):
        yield self

    async def scalars(self, _):
        return self.roles


@pytest.mark.asyncio
async def test_permission_guard_accepts_rbac_permission():
    user = SimpleNamespace(id="hr-admin")
    roles = [
        SimpleNamespace(
            role=SimpleNamespace(
                permissions=[SimpleNamespace(code=PermissionCode.USER_READ.value)]
            )
        )
    ]
    guard = require_permission(PermissionCode.USER_READ)

    assert await guard(current_user=user, session=FakeSession(roles)) is user


@pytest.mark.asyncio
async def test_permission_guard_rejects_missing_permission():
    guard = require_permission(PermissionCode.USER_READ)
    with pytest.raises(HTTPException) as exc_info:
        await guard(
            current_user=SimpleNamespace(id="employee"),
            session=FakeSession([]),
        )
    assert exc_info.value.status_code == 403
