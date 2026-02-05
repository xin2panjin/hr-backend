from fastapi import APIRouter, Depends, BackgroundTasks

from core.cache import HRCache, InviteInfoSchema
from schemas.user_schema import (
    UserLoginSchema,
    UserLoginRespSchema,
    UserInviteSchema,
    UserRegisterSchema,
    UserListRespSchema,
    UserStatusUpdateSchema,
    DepartmentListRespSchema
)
from dependencies import (
    get_session_instance,
    get_auth_handler,
    AuthHandler,
    get_cache_instance,
    get_super_user,
    get_current_user
)
from models import AsyncSession
from repository.user_repo import UserRepo, DepartmentRepo
from models.user import UserModel, UserStatus
from fastapi.exceptions import HTTPException
from fastapi import status
import string
import random
from tasks import send_invite_email_task
from schemas import ResponseSchema

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
        user: UserModel = await user_repo.get_by_email(str(login_data.email))
        if not user:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="该用户不存在！")
        # 2. 验证密码是否正确
        if not user.check_password(login_data.password):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="邮箱或密码错误！")
        # 3. 判断员工状态
        if user.status != UserStatus.ACTIVE:
            raise HTTPException(status.HTTP_403_FORBIDDEN, detail="该员工状态不可用，请联系管理员！")
        # 4. 生成JWToken
        tokens = auth_handler.encode_login_token(user.id)
        return {
            "access_token": tokens['access_token'],
            "refresh_token": tokens['refresh_token'],
            "user": user
        }

@router.post('/invite', summary="邀请用户，会给指定的邮箱发送邮件", response_model=ResponseSchema)
async def invite(
    invite_data: UserInviteSchema,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_session_instance),
    cache: HRCache = Depends(get_cache_instance),
    _: UserModel = Depends(get_super_user)
):
    email = invite_data.email
    department_id = invite_data.department_id
    async with session.begin():
        # 1. 先校验这个邮箱是否在数据库已经存在了
        user_repo = UserRepo(session)
        user: UserModel = await user_repo.get_by_email(str(email))
        if user:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="该邮箱已被注册！")
        # 2. 校验department_id在数据库中是否存在
        department_repo = DepartmentRepo(session)
        department = await department_repo.get_by_id(department_id)
        if not department:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="该部门不存在！")
    # 3. 生成邀请码
    invite_code = "".join(random.sample(string.digits, 6))
    # 4. 将邀请信息保存到缓存中
    await cache.set_invite_info(InviteInfoSchema(email=email, department_id=department_id, invite_code=invite_code))
    # 5. 给指定邮箱账号发送邮件
    # await send_invite_email_task(email, invite_code)
    background_tasks.add_task(
        send_invite_email_task,
        email=str(email),
        invite_code=invite_code,
    )
    return ResponseSchema()

@router.post("/register", summary="注册")
async def register(
    register_data: UserRegisterSchema,
    session: AsyncSession = Depends(get_session_instance),
    cache: HRCache = Depends(get_cache_instance),
):
    email = register_data.email
    # 1. 校验邮箱和邀请码是否正确
    invite_info: InviteInfoSchema = await cache.get_invite_info(str(email))
    if not invite_info:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="该邮箱账号不存在！")
    if invite_info.invite_code != register_data.invite_code:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="邀请码错误！")

    async with session.begin():
        # 3. 校验邮箱是否已经注册
        user_repo = UserRepo(session)
        user: UserModel = await user_repo.get_by_email(str(email))
        if user:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="该邮箱已被注册！")
        # 4. 创建用户
        await user_repo.create_user({
            "email": email,
            "username": register_data.username,
            "realname": register_data.realname,
            "password": register_data.password,
            "department_id": invite_info.department_id,
        })
    return ResponseSchema()

@router.get("/list", summary="获取员工列表", response_model=UserListRespSchema)
async def user_list(
    page: int = 1,
    size: int = 10,
    department_id: str|None = None,
    _: UserModel = Depends(get_super_user),
    session: AsyncSession = Depends(get_session_instance),
):
    async with session.begin():
        user_repo = UserRepo(session)
        users = await user_repo.get_user_list(page=page, size=size, department_id=department_id)
    return {"users": users}

@router.patch("/status/update", summary="修改员工状态", response_model=ResponseSchema)
async def update_status(
    status_data: UserStatusUpdateSchema,
    session: AsyncSession = Depends(get_session_instance),
    _: UserModel = Depends(get_super_user),
):
    async with session.begin():
        user_repo = UserRepo(session)
        user: UserModel = await user_repo.get_by_id(status_data.user_id)
        if not user:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="该员工不存在！")
        if user.is_superuser:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="不能修改超级用户的状态！")
        user.status = status_data.status
    return ResponseSchema()

@router.get("/department/list", summary="获取所有部门列表", response_model=DepartmentListRespSchema)
async def department_list(
    session: AsyncSession = Depends(get_session_instance),
    _: str = Depends(get_current_user),
):
    async with session.begin():
        department_repo = DepartmentRepo(session)
        departments = await department_repo.get_department_list()
        return {"departments": departments}