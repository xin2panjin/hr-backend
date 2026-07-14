from core.cache import HRCache
from models import AsyncSessionFactory, AsyncSession
from core.auth import AuthHandler
from fastapi import Depends, HTTPException, status

from models.user import UserModel, UserStatus
from repository.user_repo import UserRepo
from repository.iam_repo import IamRepo
from iam.permissions import PermissionCode

auth_handler = AuthHandler()

async def get_session_instance():
    session: AsyncSession = AsyncSessionFactory()
    try:
        yield session
    finally:
        await session.close()

async def get_auth_handler():
    return auth_handler

def get_access_token_claims(
    claims: dict = Depends(auth_handler.auth_access_dependency),
) -> dict:
    return claims


def get_user_id(claims: dict = Depends(get_access_token_claims)) -> str:
    return str(claims["sub"])


def get_refresh_token_claims(
    claims: dict = Depends(auth_handler.auth_refresh_dependency),
) -> dict:
    return claims

async def get_current_user(
    user_id: str = Depends(get_user_id),
    token_claims: dict = Depends(get_access_token_claims),
    session: AsyncSession = Depends(get_session_instance)
) -> UserModel:
    async with session.begin():
        user_repo = UserRepo(session)
        user: UserModel = await user_repo.get_by_id(user_id)
        if not user:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="该用户不存在！")
        if user.status != UserStatus.ACTIVE:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="该账号不可用，请联系管理员！")
        from iam.services.auth_session_service import AuthSessionService, SessionValidationError

        try:
            await AuthSessionService(session).validate_access_claims(
                claims=token_claims,
                user=user,
            )
        except SessionValidationError as exc:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc
        # 资源 Policy 统一从此处携带的有效角色和范围读取授权上下文，避免再查询旧布尔字段。
        user.iam_roles = await IamRepo(session).get_active_user_roles(user.id)
        return user

def require_permission(permission: PermissionCode):
    """统一的 RBAC 权限守卫。"""

    async def permission_guard(
        current_user: UserModel = Depends(get_current_user),
        session: AsyncSession = Depends(get_session_instance),
    ) -> UserModel:
        async with session.begin():
            user_roles = await IamRepo(session).get_active_user_roles(current_user.id)
        if any(
            permission.value in {item.code for item in user_role.role.permissions}
            for user_role in user_roles
        ):
            return current_user
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="权限不足，无法访问！")

    return permission_guard


def get_cache_instance():
    return HRCache()
