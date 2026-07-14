from datetime import datetime
from types import SimpleNamespace

import pytest

from repository.iam_repo import IamRepo


class FakeSession:
    def __init__(self):
        self.statements = []

    async def scalars(self, statement):
        self.statements.append(statement)
        return [SimpleNamespace(id="audit-1"), SimpleNamespace(id="audit-2")]

    async def scalar(self, statement):
        self.statements.append(statement)
        return 2


@pytest.mark.asyncio
async def test_audit_log_query_returns_paginated_rows_and_total():
    session = FakeSession()
    items, total = await IamRepo(session).get_audit_logs(
        page=2,
        size=10,
        actor_id="admin-1",
        action="user_role.grant",
        target_type="user_role",
        target_id="user-1",
        started_at=datetime(2026, 1, 1),
        ended_at=datetime(2026, 1, 2),
    )

    assert [item.id for item in items] == ["audit-1", "audit-2"]
    assert total == 2
    assert len(session.statements) == 2
