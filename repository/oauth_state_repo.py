from sqlalchemy import select

from models.iam import OAuthStateModel

from . import BaseRepo


class OAuthStateRepo(BaseRepo):
    async def get_for_consume(self, *, provider: str, state_hash: str) -> OAuthStateModel | None:
        return await self.session.scalar(
            select(OAuthStateModel)
            .where(OAuthStateModel.provider == provider, OAuthStateModel.state_hash == state_hash)
            .with_for_update()
        )
