from datetime import datetime, timedelta
from types import SimpleNamespace

import jwt
import pytest
from fastapi import HTTPException

from core.auth import AuthHandler
from iam.services.auth_session_service import AuthSessionService, PasswordChangeError, SessionValidationError
from models.user import UserModel, UserStatus
from settings import settings


class FakeSession:
    def __init__(self):
        self.added = []

    def add(self, item):
        self.added.append(item)


class FakeSessionRepo:
    def __init__(self, auth_session):
        self.auth_session = auth_session
        self.revoke_calls = []

    async def get_by_id(self, _):
        return self.auth_session

    async def get_by_id_for_update(self, _):
        return self.auth_session

    async def revoke_user_sessions(self, *, user_id, reason):
        self.revoke_calls.append((user_id, reason))
        return 1


class FakeUserRepo:
    def __init__(self, user):
        self.user = user

    async def get_by_id(self, _):
        return self.user


def build_user():
    return SimpleNamespace(id="user-1", status=UserStatus.ACTIVE, authz_version=3, last_login_at=None)


def test_new_jwt_uses_standard_session_claims_and_rejects_wrong_type():
    auth_handler = AuthHandler()
    tokens = auth_handler.issue_session_tokens(user_id="user-1", session_id="session-1", authz_version=3)

    access_claims = auth_handler.decode_access_token(tokens["access_token"])
    assert access_claims["sub"] == "user-1"
    assert access_claims["sid"] == "session-1"
    assert access_claims["typ"] == "access"
    assert access_claims["ver"] == 3

    with pytest.raises(HTTPException):
        auth_handler.decode_access_token(tokens["refresh_token"])


def test_legacy_jwt_is_only_accepted_as_compatibility_claims():
    legacy_token = jwt.encode(
        {"iss": "legacy-user", "sub": "1", "exp": int((datetime.now() + timedelta(minutes=5)).timestamp())},
        settings.JWT_SECRET_KEY,
        algorithm="HS256",
    )

    assert AuthHandler().decode_access_token(legacy_token) == {"sub": "legacy-user", "legacy": True}


@pytest.mark.asyncio
async def test_access_session_validation_checks_authz_version_and_revocation():
    user = build_user()
    auth_session = SimpleNamespace(
        user_id=user.id,
        authz_version=3,
        revoked_at=None,
        expires_at=datetime.now() + timedelta(days=1),
        last_seen_at=None,
    )
    service = AuthSessionService(FakeSession())
    service.session_repo = FakeSessionRepo(auth_session)
    claims = {"sid": "session-1", "ver": 3}

    await service.validate_access_claims(claims=claims, user=user)
    assert auth_session.last_seen_at is not None

    user.authz_version = 4
    with pytest.raises(SessionValidationError, match="失效"):
        await service.validate_access_claims(claims=claims, user=user)


@pytest.mark.asyncio
async def test_refresh_rotation_revokes_all_sessions_when_old_refresh_is_reused():
    user = build_user()
    auth_handler = AuthHandler()
    original = auth_handler.issue_session_tokens(user_id=user.id, session_id="session-1", authz_version=3)
    auth_session = SimpleNamespace(
        id="session-1",
        user_id=user.id,
        authz_version=3,
        refresh_jti_hash=auth_handler.hash_jti(str(original["refresh_claims"]["jti"])),
        expires_at=datetime.now() + timedelta(days=1),
        revoked_at=None,
        revoke_reason=None,
        replaced_by_id=None,
    )
    session = FakeSession()
    service = AuthSessionService(session, auth_handler)
    session_repo = FakeSessionRepo(auth_session)
    service.session_repo = session_repo
    service.user_repo = FakeUserRepo(user)

    rotated = await service.rotate_refresh_token(original["refresh_claims"])
    assert rotated["access_token"]
    assert auth_session.revoke_reason == "refresh_rotated"
    assert auth_session.replaced_by_id

    with pytest.raises(SessionValidationError, match="失效"):
        await service.rotate_refresh_token(original["refresh_claims"])
    assert session_repo.revoke_calls == [(user.id, "refresh_token_reuse")]


@pytest.mark.asyncio
async def test_change_my_password_requires_current_password_and_revokes_sessions():
    user = UserModel(
        id="user-1",
        username="test.user",
        email="test.user@example.com",
        realname="Test User",
        password="OldPassword!2026",
        status=UserStatus.ACTIVE,
        authz_version=3,
    )
    session = FakeSession()
    service = AuthSessionService(session)
    session_repo = FakeSessionRepo(None)
    service.session_repo = session_repo

    with pytest.raises(PasswordChangeError, match="当前密码"):
        await service.change_my_password(
            user=user,
            current_password="WrongPassword!2026",
            new_password="NewPassword!2026",
        )

    await service.change_my_password(
        user=user,
        current_password="OldPassword!2026",
        new_password="NewPassword!2026",
    )

    assert user.check_password("NewPassword!2026")
    assert user.authz_version == 4
    assert session_repo.revoke_calls == [(user.id, "password_changed")]
    assert {item.action for item in session.added} >= {"session.revoke_all", "user.password.change"}
