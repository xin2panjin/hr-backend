"""登录会话、刷新轮换与集中撤销。"""

from __future__ import annotations

import uuid
from datetime import datetime

from core.auth import AuthHandler
from models.iam import AuditLogModel, AuthSessionModel
from models.user import UserModel, UserStatus
from repository.auth_session_repo import AuthSessionRepo
from repository.user_repo import UserRepo
from settings import settings
from iam.services.password_policy import validate_password


class SessionValidationError(ValueError):
    pass


class AuthSessionService:
    def __init__(self, session, auth_handler: AuthHandler | None = None):
        self.session = session
        self.auth_handler = auth_handler or AuthHandler()
        self.session_repo = AuthSessionRepo(session)
        self.user_repo = UserRepo(session)

    async def create_login_session(self, user: UserModel) -> dict[str, object]:
        session_id = uuid.uuid4().hex
        tokens = self.auth_handler.issue_session_tokens(
            user_id=user.id,
            session_id=session_id,
            authz_version=user.authz_version,
        )
        refresh_claims = tokens["refresh_claims"]
        auth_session = AuthSessionModel(
            id=session_id,
            user_id=user.id,
            authz_version=user.authz_version,
            refresh_jti_hash=self.auth_handler.hash_jti(str(refresh_claims["jti"])),
            expires_at=datetime.fromtimestamp(int(refresh_claims["exp"])),
            last_seen_at=datetime.now(),
        )
        self.session.add(auth_session)
        user.last_login_at = datetime.now()
        return tokens

    async def validate_access_claims(self, *, claims: dict[str, object], user: UserModel) -> None:
        if claims.get("legacy"):
            return
        if int(claims.get("ver", -1)) != user.authz_version:
            raise SessionValidationError("登录状态已失效，请重新登录")
        auth_session = await self.session_repo.get_by_id(str(claims["sid"]))
        if (
            not auth_session
            or auth_session.user_id != user.id
            or auth_session.revoked_at
            or auth_session.expires_at <= datetime.now()
            or auth_session.authz_version != user.authz_version
        ):
            raise SessionValidationError("登录会话已失效，请重新登录")
        auth_session.last_seen_at = datetime.now()

    async def rotate_refresh_token(self, claims: dict[str, object]) -> dict[str, object]:
        if claims.get("legacy"):
            raise SessionValidationError("旧版刷新令牌不支持续期，请重新登录")
        session_id = str(claims["sid"])
        auth_session = await self.session_repo.get_by_id_for_update(session_id)
        if not auth_session:
            raise SessionValidationError("登录会话不存在")
        user = await self.user_repo.get_by_id(auth_session.user_id)
        if not user or user.status != UserStatus.ACTIVE:
            raise SessionValidationError("账号不可用")
        if auth_session.revoked_at or auth_session.expires_at <= datetime.now():
            if auth_session.revoke_reason == "refresh_rotated":
                await self.revoke_user_sessions(user_id=user.id, reason="refresh_token_reuse")
            raise SessionValidationError("刷新令牌已失效，请重新登录")
        if (
            auth_session.authz_version != user.authz_version
            or int(claims.get("ver", -1)) != user.authz_version
            or not hmac_compare(
                auth_session.refresh_jti_hash,
                self.auth_handler.hash_jti(str(claims["jti"])),
            )
        ):
            await self.revoke_user_sessions(user_id=user.id, reason="refresh_token_reuse")
            raise SessionValidationError("刷新令牌已失效，请重新登录")

        new_session_id = uuid.uuid4().hex
        tokens = self.auth_handler.issue_session_tokens(
            user_id=user.id,
            session_id=new_session_id,
            authz_version=user.authz_version,
        )
        refresh_claims = tokens["refresh_claims"]
        new_session = AuthSessionModel(
            id=new_session_id,
            user_id=user.id,
            authz_version=user.authz_version,
            refresh_jti_hash=self.auth_handler.hash_jti(str(refresh_claims["jti"])),
            expires_at=datetime.fromtimestamp(int(refresh_claims["exp"])),
            last_seen_at=datetime.now(),
        )
        self.session.add(new_session)
        auth_session.revoked_at = datetime.now()
        auth_session.revoke_reason = "refresh_rotated"
        auth_session.replaced_by_id = new_session_id
        self._audit(actor_id=user.id, action="session.refresh", target_id=new_session_id)
        return tokens

    async def revoke_user_sessions(self, *, user_id: str, reason: str, actor_id: str | None = None) -> int:
        count = await self.session_repo.revoke_user_sessions(user_id=user_id, reason=reason)
        self._audit(
            actor_id=actor_id,
            action="session.revoke_all",
            target_id=user_id,
            after_data={"count": count, "reason": reason},
        )
        return count

    async def revoke_session(
        self,
        *,
        user_id: str,
        session_id: str,
        reason: str,
        actor_id: str,
    ) -> bool:
        auth_session = await self.session_repo.get_by_id_for_update(session_id)
        if not auth_session or auth_session.user_id != user_id or auth_session.revoked_at:
            return False
        auth_session.revoked_at = datetime.now()
        auth_session.revoke_reason = reason
        self._audit(actor_id=actor_id, action="session.revoke", target_id=session_id)
        return True

    async def reset_password(self, *, user: UserModel, new_password: str, actor_id: str) -> None:
        validate_password(new_password, username=user.username, email=user.email)
        user.password = new_password
        user.authz_version += 1
        await self.revoke_user_sessions(user_id=user.id, reason="password_reset", actor_id=actor_id)
        self._audit(actor_id=actor_id, action="user.password.reset", target_id=user.id)

    def _audit(self, *, actor_id: str | None, action: str, target_id: str, after_data=None) -> None:
        self.session.add(AuditLogModel(actor_id=actor_id, action=action, target_type="auth_session", target_id=target_id, after_data=after_data))


def hmac_compare(left: str, right: str) -> bool:
    import hmac

    return hmac.compare_digest(left, right)
