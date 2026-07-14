"""认证会话持久化读取与撤销。"""

from datetime import datetime

from sqlalchemy import select, update

from models.iam import AuthSessionModel

from . import BaseRepo


class AuthSessionRepo(BaseRepo):
    async def get_by_id(self, session_id: str) -> AuthSessionModel | None:
        return await self.session.scalar(
            select(AuthSessionModel).where(AuthSessionModel.id == session_id)
        )

    async def get_by_id_for_update(self, session_id: str) -> AuthSessionModel | None:
        return await self.session.scalar(
            select(AuthSessionModel)
            .where(AuthSessionModel.id == session_id)
            .with_for_update()
        )

    async def list_user_sessions(self, user_id: str) -> list[AuthSessionModel]:
        result = await self.session.scalars(
            select(AuthSessionModel)
            .where(AuthSessionModel.user_id == user_id)
            .order_by(AuthSessionModel.last_seen_at.desc().nullslast(), AuthSessionModel.created_at.desc())
        )
        return list(result)

    async def revoke_user_sessions(self, *, user_id: str, reason: str) -> int:
        result = await self.session.execute(
            update(AuthSessionModel)
            .where(AuthSessionModel.user_id == user_id, AuthSessionModel.revoked_at.is_(None))
            .values(revoked_at=datetime.now(), revoke_reason=reason)
        )
        return int(result.rowcount or 0)
