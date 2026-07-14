import hashlib
import hmac
import secrets
from datetime import datetime, timedelta

from models.iam import OAuthStateModel
from repository.oauth_state_repo import OAuthStateRepo
from settings import settings


class OAuthStateValidationError(ValueError):
    pass


class OAuthStateService:
    STATE_TTL_MINUTES = 10

    def __init__(self, session):
        self.session = session
        self.repo = OAuthStateRepo(session)

    async def create_state(self, *, provider: str, user_id: str, redirect_uri: str) -> str:
        state = secrets.token_urlsafe(32)
        self.session.add(OAuthStateModel(
            provider=provider,
            state_hash=self.hash_state(state),
            user_id=user_id,
            redirect_uri=redirect_uri,
            expires_at=datetime.now() + timedelta(minutes=self.STATE_TTL_MINUTES),
        ))
        return state

    async def consume_state(self, *, provider: str, state: str) -> str:
        record = await self.repo.get_for_consume(provider=provider, state_hash=self.hash_state(state))
        if not record or record.consumed_at or record.expires_at <= datetime.now():
            raise OAuthStateValidationError("OAuth state 不存在、已失效或已使用")
        record.consumed_at = datetime.now()
        return record.user_id

    @staticmethod
    def hash_state(state: str) -> str:
        return hmac.new(settings.JWT_SECRET_KEY.encode(), state.encode(), hashlib.sha256).hexdigest()
