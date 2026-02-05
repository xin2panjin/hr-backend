from core.single import SingletonMeta
from fastapi_cache import FastAPICache
from fastapi_cache.backends.redis import RedisBackend
from pydantic import BaseModel, EmailStr
from settings import settings


class InviteInfoSchema(BaseModel):
    email: EmailStr
    department_id: str
    invite_code: str

class DingTalkTokenInfoSchema(BaseModel):
    access_token: str
    refresh_token: str
    user_id: str


class HRCache(metaclass=SingletonMeta):
    invite_prefix = "invite:"
    dingtalk_prefix = "dingtalk:"

    def __init__(self):
        self.cache_backend: RedisBackend = FastAPICache.get_backend()

    async def set(self, key, value, ex: int):
        await self.cache_backend.set(key, value, expire=ex if ex else None)

    async def get(self, key):
        value = await self.cache_backend.get(key)
        return value

    async def delete(self, key):
        await self.cache_backend.clear(key)

    async def set_invite_info(self, invite_info: InviteInfoSchema):
        key = f"{self.invite_prefix}{invite_info.email}"
        await self.set(key, invite_info.model_dump_json(), ex=settings.INVITE_CODE_EXPIRE)

    async def get_invite_info(self, email: str) -> InviteInfoSchema | None:
        key = f"{self.invite_prefix}{email}"
        invite_info_json = await self.get(key)
        if invite_info_json is not None:
            invite_info = InviteInfoSchema.model_validate_json(invite_info_json)
            return invite_info
        return None

    async def set_dingtalk_info(self, dingtalk_info: DingTalkTokenInfoSchema):
        key = f"{self.dingtalk_prefix}{dingtalk_info.user_id}"
        await self.set(key, dingtalk_info.model_dump_json(), ex=60*60*24*29)

    async def get_dingtalk_info(self, user_id: str):
        key = f"{self.dingtalk_prefix}{user_id}"
        return await self.get(key)
