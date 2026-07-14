from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from iam.services.oauth_state_service import OAuthStateService, OAuthStateValidationError


class FakeSession:
    def __init__(self):
        self.added = []

    def add(self, item):
        self.added.append(item)


class FakeRepo:
    def __init__(self, record):
        self.record = record
        self.calls = []

    async def get_for_consume(self, **kwargs):
        self.calls.append(kwargs)
        return self.record


@pytest.mark.asyncio
async def test_oauth_state_is_random_and_only_hash_is_persisted():
    session = FakeSession()
    service = OAuthStateService(session)

    state = await service.create_state(
        provider="dingtalk",
        user_id="user-1",
        redirect_uri="https://example.test/callback",
    )

    record = session.added[0]
    assert len(state) >= 32
    assert record.state_hash == service.hash_state(state)
    assert state != record.state_hash


@pytest.mark.asyncio
async def test_oauth_state_can_only_be_consumed_once_before_expiry():
    service = OAuthStateService(FakeSession())
    record = SimpleNamespace(
        user_id="user-1",
        consumed_at=None,
        expires_at=datetime.now() + timedelta(minutes=1),
    )
    repo = FakeRepo(record)
    service.repo = repo

    assert await service.consume_state(provider="dingtalk", state="opaque-state") == "user-1"
    assert record.consumed_at is not None

    with pytest.raises(OAuthStateValidationError, match="已使用"):
        await service.consume_state(provider="dingtalk", state="opaque-state")
