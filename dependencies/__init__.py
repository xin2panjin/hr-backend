from core.cache import HRCache
from models import AsyncSessionFactory, AsyncSession
from core.auth import AuthHandler
from fastapi import Depends, HTTPException, status

from models.user import UserModel, UserStatus
from repository.user_repo import UserRepo

auth_handler = AuthHandler()

async def get_session_instance():
    session: AsyncSession = AsyncSessionFactory()
    try:
        yield session
    finally:
        await session.close()

async def get_auth_handler():
    return auth_handler

def get_user_id(
    iss: str = Depends(auth_handler.auth_access_dependency)
) -> str:
    return iss

async def get_current_user(
    user_id: str = Depends(get_user_id),
    session: AsyncSession = Depends(get_session_instance)
) -> UserModel:
    async with session.begin():
        user_repo = UserRepo(session)
        user: UserModel = await user_repo.get_by_id(user_id)
        if not user:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="该用户不存在！")
        if user.status != UserStatus.ACTIVE:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="该账号不可用，请联系管理员！")
        return user

async def get_super_user(
    current_user: UserModel = Depends(get_current_user),
) -> UserModel:
    if current_user.is_superuser:
        return current_user
    else:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="权限不足，无法访问！")

def get_cache_instance():
    return HRCache()