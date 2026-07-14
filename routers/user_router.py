from fastapi import APIRouter, Depends

from core.cache import HRCache, DingTalkTokenInfoSchema
from schemas.user_schema import (
    UserLoginSchema,
    UserLoginRespSchema,
    UserRegisterSchema,
    DingdingUserRespSchema,
)
from dependencies import (
    get_session_instance,
    get_auth_handler,
    AuthHandler,
    get_cache_instance,
    get_current_user,
    get_refresh_token_claims,
)
from models import AsyncSession
from repository.user_repo import UserRepo
from models.user import UserModel, UserStatus
from fastapi.exceptions import HTTPException
from fastapi import status
from iam.services.invitation_service import (
    InvitationConflict,
    InvitationService,
    InvitationValidationError,
)
from iam.services.auth_session_service import AuthSessionService, SessionValidationError
from iam.services.password_policy import PasswordPolicyError
from iam.services.oauth_state_service import OAuthStateService, OAuthStateValidationError
from schemas import ResponseSchema
from schemas.user_schema import TokenPairSchema
from settings import settings
from urllib.parse import urlencode, urljoin
from core.dingtalk import DingTalkApi
from fastapi.templating import Jinja2Templates
# httpx： uv add httpx
import httpx
from fastapi import Request
from fastapi.responses import RedirectResponse

jinja2Engine = Jinja2Templates(directory="templates")

# ApiFox

# /docs
router = APIRouter(prefix="/user", tags=["user"])

@router.post("/login", summary="登录", response_model=UserLoginRespSchema)
async def login(
    login_data: UserLoginSchema,
    session: AsyncSession = Depends(get_session_instance),
    auth_handler: AuthHandler = Depends(get_auth_handler),
):
    # 开启事务
    async with session.begin():
        # 1. 获取用户
        user_repo = UserRepo(session)
        user: UserModel = await user_repo.get_by_login_account(login_data.account)
        if not user:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="该用户不存在！")
        # 2. 验证密码是否正确
        if not user.check_password(login_data.password):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="邮箱或密码错误！")
        # 3. 判断员工状态
        if user.status != UserStatus.ACTIVE:
            raise HTTPException(status.HTTP_403_FORBIDDEN, detail="该员工状态不可用，请联系管理员！")
        # 4. 创建服务端会话并签发绑定 sid/authz_version 的令牌对。
        tokens = await AuthSessionService(session, auth_handler).create_login_session(user)
        return {
            "access_token": tokens['access_token'],
            "refresh_token": tokens['refresh_token'],
            "user": user
        }


@router.post("/refresh", summary="轮换刷新令牌", response_model=TokenPairSchema)
async def refresh_login_token(
    refresh_claims: dict = Depends(get_refresh_token_claims),
    session: AsyncSession = Depends(get_session_instance),
    auth_handler: AuthHandler = Depends(get_auth_handler),
):
    try:
        async with session.begin():
            tokens = await AuthSessionService(session, auth_handler).rotate_refresh_token(
                refresh_claims
            )
    except SessionValidationError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc
    return {"access_token": tokens["access_token"], "refresh_token": tokens["refresh_token"]}
@router.post("/register", summary="注册")
async def register(
    register_data: UserRegisterSchema,
    session: AsyncSession = Depends(get_session_instance),
):
    email = register_data.email
    async with session.begin():
        try:
            user = await InvitationService(session).register_from_invitation(
                email=str(email),
                invite_code=register_data.invite_code,
                user_data={
                    "username": register_data.username,
                    "realname": register_data.realname,
                    "password": register_data.password,
                },
            )
        except InvitationValidationError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
        except InvitationConflict as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
        except PasswordPolicyError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    return ResponseSchema()

@router.get("/dingtalk/authorize", summary="获取登录钉钉的URL")
async def dingtalk_authorize(
    current_user: UserModel = Depends(get_current_user),
    session: AsyncSession = Depends(get_session_instance),
):
    # redirect_uri：必须是公网能够访问的url
    redirect_uri = urljoin(settings.BACKEND_BASE_URL, "/user/dingtalk/callback")
    async with session.begin():
        state = await OAuthStateService(session).create_state(
            provider="dingtalk",
            user_id=current_user.id,
            redirect_uri=redirect_uri,
        )
    params = {
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "client_id": settings.DINGTALK_CLIENT_ID,
        "scope": "openid",
        "state": state,
        "prompt": "consent"
    }
    authorize_url = f"https://login.dingtalk.com/oauth2/auth?{urlencode(params)}"
    return {"authorize_url": authorize_url}

@router.get("/dingtalk/callback")
async def dingtalk_callback(
    state: str,
    code: str | None = None,
    authCode: str | None = None,
    session: AsyncSession = Depends(get_session_instance),
    cache: HRCache = Depends(get_cache_instance)
):
    try:
        async with session.begin():
            user_id = await OAuthStateService(session).consume_state(
                provider="dingtalk",
                state=state,
            )
    except OAuthStateValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    authorization_code = authCode or code
    if not authorization_code:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="缺少钉钉授权码")
    async with httpx.AsyncClient() as client:
        # 1. 获取token
        token_resp = await client.post(
            url=DingTalkApi.build_access_token_url(),
            json={
                "clientId": settings.DINGTALK_CLIENT_ID,
                "clientSecret": settings.DINGTALK_CLIENT_SECRET,
                "code": authorization_code,
                "grantType": "authorization_code"
            }
        )
        if token_resp.status_code != 200:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="钉钉Token获取失败！")
        token_data = token_resp.json()
        access_token = token_data["accessToken"]
        refresh_token = token_data["refreshToken"]
        # 2. 存储token
        await cache.set_dingtalk_info(DingTalkTokenInfoSchema(
            access_token=access_token,
            refresh_token=refresh_token,
            user_id=user_id
        ))
        # 3. 利用token获取用户的信息
        my_info_resp = await client.get(
            url=DingTalkApi.build_get_my_info_url(),
            headers={
                "x-acs-dingtalk-access-token": access_token,
            }
        )
        if my_info_resp.status_code != 200:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="钉钉个人信息获取失败！")
        my_info = my_info_resp.json()
        nick = my_info["nick"]
        mobile = my_info["mobile"]
        open_id = my_info["openId"]
        union_id = my_info["unionId"]
        # 4. 保存钉钉上用户的数据到数据库中
        async with session.begin():
            user_repo = UserRepo(session)
            await user_repo.set_dingding_user(
                user_id=user_id,
                dingding_user_data={
                    "nick": nick,
                    "mobile": mobile,
                    "open_id": open_id,
                    "union_id": union_id,
                }
            )
        # 5. 跳转到成功的页面
        return RedirectResponse(f"/user/dingtalk/authorize/success?nick={nick}")

@router.get("/dingtalk/authorize/success")
async def dingtalk_authorize_success(
    nick: str,
    request: Request,
):
    return jinja2Engine.TemplateResponse(
        "ding_authorize_success.html",
        {"username": nick, "request": request}
    )

@router.get("/dingtalk/account", summary="获取自己的钉钉账号", response_model=DingdingUserRespSchema)
async def dingtalk_account(
    session: AsyncSession = Depends(get_session_instance),
    current_user: UserModel = Depends(get_current_user),
):
    async with session.begin():
        user_repo = UserRepo(session)
        dingding_user = await user_repo.get_dingding_user(current_user.id)
    return {"dingding_user": dingding_user}
