"""IAM 管理端接口。

当前沿用超级管理员依赖作为兼容保护；RBAC 双读完成并切换后，会替换为
permission guard，而不再让业务 Router 判断旧布尔字段。
"""

from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from sqlalchemy.exc import IntegrityError

from dependencies import get_access_token_claims, get_current_user, get_session_instance, require_permission
from iam.services.organization_service import (
    DepartmentArchiveConflict,
    OrganizationService,
    OrganizationValidationError,
)
from iam.services.role_assignment_service import (
    RoleAssignmentConflict,
    RoleAssignmentService,
    RoleAssignmentValidationError,
)
from iam.services.role_permission_service import (
    RolePermissionService,
    RolePermissionValidationError,
)
from iam.services.invitation_service import (
    InvitationConflict,
    InvitationService,
    InvitationValidationError,
)
from iam.services.auth_session_service import AuthSessionService
from iam.services.password_policy import PasswordPolicyError
from iam.permissions import PERMISSION_VIEW_GROUPS, PERMISSION_VIEW_METADATA, PermissionCode
from models import AsyncSession
from models.user import DepartmentStatus, UserModel, UserStatus
from repository.iam_repo import IamRepo
from repository.auth_session_repo import AuthSessionRepo
from repository.user_repo import DepartmentRepo, UserRepo
from schemas.iam_schema import (
    AuditLogListSchema,
    AuthSessionSchema,
    DepartmentCreateSchema,
    DepartmentDependencySchema,
    DepartmentSummarySchema,
    DepartmentUpdateSchema,
    IamDepartmentSchema,
    IamDepartmentTreeNodeSchema,
    IamPrincipalSchema,
    IamPermissionSchema,
    IamInvitationCreateSchema,
    IamInvitationSchema,
    IamRoleSchema,
    IamUserListSchema,
    IamUserSchema,
    IamUserStatusUpdateSchema,
    PrincipalRoleSchema,
    RolePermissionTreeSchema,
    RolePermissionUpdateSchema,
    UserRoleGrantSchema,
    UserRoleRevokeSchema,
    UserRoleSchema,
    UserRoleScopeReplaceSchema,
    UserPasswordResetSchema,
    UserProfileUpdateSchema,
)
from tasks.email_tasks import send_invite_email_task


router = APIRouter(prefix="/iam", tags=["IAM"])


def _serialize_user(user: UserModel, role_codes: list[str] | None = None) -> dict:
    return {
        "id": user.id,
        "username": user.username,
        "email": user.email,
        "realname": user.realname,
        "phone_number": user.phone_number,
        "department_id": user.department_id,
        "department": user.department,
        "status": user.status,
        "authz_version": user.authz_version,
        "disabled_at": user.disabled_at,
        "created_at": user.created_at,
        "role_codes": sorted(role_codes or []),
    }


def _serialize_user_role(user_role) -> dict:
    return {
        "id": user_role.id,
        "user_id": user_role.user_id,
        "role_code": user_role.role.code,
        "assigned_by": user_role.assigned_by,
        "assigned_at": user_role.assigned_at,
        "expires_at": user_role.expires_at,
        "revoked_at": user_role.revoked_at,
        "revoke_reason": user_role.revoke_reason,
        "department_ids": sorted(
            str(scope.department_id) for scope in user_role.scopes if scope.department_id
        ),
    }


def _serialize_invitation(invitation) -> dict:
    return {
        "id": invitation.id,
        "email": invitation.email,
        "username": invitation.username,
        "department_id": invitation.department_id,
        "role_code": invitation.role.code,
        "department_scope_ids": invitation.department_scope_ids,
        "expires_at": invitation.expires_at,
        "used_at": invitation.used_at,
        "cancelled_at": invitation.cancelled_at,
        "created_at": invitation.created_at,
    }


def _serialize_auth_session(auth_session, current_session_id: str | None) -> dict:
    return {
        "id": auth_session.id,
        "created_at": auth_session.created_at,
        "last_seen_at": auth_session.last_seen_at,
        "expires_at": auth_session.expires_at,
        "revoked_at": auth_session.revoked_at,
        "revoke_reason": auth_session.revoke_reason,
        "is_current": auth_session.id == current_session_id,
    }


def _serialize_role_permission_tree(role) -> dict:
    """将内部权限码转换为仅包含业务语言的前端树形契约。"""

    selected_ids = {permission.id for permission in role.permissions}
    modules: dict[str, dict] = {}
    for permission in sorted(role.permissions, key=lambda item: (item.resource, item.action)):
        module_name, _ = PERMISSION_VIEW_GROUPS.get(permission.resource, ("其他能力", 999))
        item_name, item_description = PERMISSION_VIEW_METADATA.get(
            permission.code,
            (permission.name, permission.description),
        )
        modules.setdefault(module_name, {"name": module_name, "permissions": []})[
            "permissions"
        ].append(
            {
                "id": permission.id,
                "name": item_name,
                "description": item_description,
                "checked": permission.id in selected_ids,
            }
        )

    # 编辑页需要同时看到未授予的既有权限项，因此由调用方传入的 role 会临时挂载全量目录。
    return {"role_id": role.id, "role_name": role.name, "modules": list(modules.values())}


def _serialize_role_permission_tree_from_catalog(role, permissions) -> dict:
    selected_ids = {permission.id for permission in role.permissions}
    modules: dict[str, dict] = {}
    for permission in sorted(permissions, key=lambda item: (item.resource, item.action)):
        module_name, module_order = PERMISSION_VIEW_GROUPS.get(permission.resource, ("其他能力", 999))
        item_name, item_description = PERMISSION_VIEW_METADATA.get(
            permission.code,
            (permission.name, permission.description),
        )
        module = modules.setdefault(
            module_name,
            {"name": module_name, "order": module_order, "permissions": []},
        )
        module["permissions"].append(
            {
                "id": permission.id,
                "name": item_name,
                "description": item_description,
                "checked": permission.id in selected_ids,
            }
        )
    return {
        "role_id": role.id,
        "role_name": role.name,
        "modules": [
            {"name": module["name"], "permissions": module["permissions"]}
            for module in sorted(modules.values(), key=lambda item: (item["order"], item["name"]))
        ],
    }


async def _get_user_or_404(user_id: str, user_repo: UserRepo) -> UserModel:
    user = await user_repo.get_by_id(user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户不存在")
    return user


async def _get_department_or_404(
    department_id: str,
    department_repo: DepartmentRepo,
) -> object:
    department = await department_repo.get_by_id(department_id)
    if not department:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="部门不存在")
    return department


@router.get("/me", response_model=IamPrincipalSchema, summary="获取当前 IAM 主体")
async def get_current_principal(
    current_user: UserModel = Depends(get_current_user),
    session: AsyncSession = Depends(get_session_instance),
):
    async with session.begin():
        user_roles = await IamRepo(session).get_active_user_roles(current_user.id)
        role_schemas = [
            PrincipalRoleSchema(
                code=user_role.role.code,
                name=user_role.role.name,
                expires_at=user_role.expires_at,
                department_ids=sorted(
                    str(scope.department_id)
                    for scope in user_role.scopes
                    if scope.department_id
                ),
            )
            for user_role in user_roles
        ]
        permissions = sorted(
            {
                permission.code
                for user_role in user_roles
                for permission in user_role.role.permissions
            }
        )
    return {
        "user": _serialize_user(current_user, [role.code for role in role_schemas]),
        "roles": role_schemas,
        "permissions": permissions,
    }


@router.get("/roles", response_model=list[IamRoleSchema], summary="查询固定角色及权限")
async def list_roles(
    _: UserModel = Depends(require_permission(PermissionCode.ROLE_READ)),
    session: AsyncSession = Depends(get_session_instance),
):
    async with session.begin():
        roles = await IamRepo(session).list_roles()
    return [
        {
            "id": role.id,
            "code": role.code,
            "name": role.name,
            "description": role.description,
            "is_system": role.is_system,
            "permissions": sorted(permission.code for permission in role.permissions),
        }
        for role in roles
    ]


@router.get(
    "/roles/{role_id}/permissions",
    response_model=RolePermissionTreeSchema,
    summary="查看角色权限树",
)
async def get_role_permissions(
    role_id: str,
    _: UserModel = Depends(require_permission(PermissionCode.ROLE_READ)),
    session: AsyncSession = Depends(get_session_instance),
):
    async with session.begin():
        iam_repo = IamRepo(session)
        role = await iam_repo.get_role_by_id(role_id)
        if not role:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="角色不存在")
        permissions = await iam_repo.list_permissions()
        return _serialize_role_permission_tree_from_catalog(role, permissions)


@router.put(
    "/roles/{role_id}/permissions",
    response_model=RolePermissionTreeSchema,
    summary="编辑角色权限树",
)
async def replace_role_permissions(
    role_id: str,
    payload: RolePermissionUpdateSchema,
    current_admin: UserModel = Depends(require_permission(PermissionCode.ROLE_UPDATE_PERMISSIONS)),
    session: AsyncSession = Depends(get_session_instance),
):
    try:
        async with session.begin():
            iam_repo = IamRepo(session)
            role = await iam_repo.get_role_by_id(role_id)
            if not role:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="角色不存在")
            await RolePermissionService(session).replace_permissions(
                role=role,
                permission_ids=payload.permission_ids,
                reason=payload.reason,
                actor_id=current_admin.id,
            )
            await session.flush()
            permissions = await iam_repo.list_permissions()
            return _serialize_role_permission_tree_from_catalog(role, permissions)
    except RolePermissionValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc


@router.get("/permissions", response_model=list[IamPermissionSchema], summary="查询固定权限码字典")
async def list_permissions(
    _: UserModel = Depends(require_permission(PermissionCode.ROLE_READ)),
    session: AsyncSession = Depends(get_session_instance),
):
    async with session.begin():
        return await IamRepo(session).list_permissions()


@router.get("/audit-logs", response_model=AuditLogListSchema, summary="分页查询 IAM 审计日志")
async def list_audit_logs(
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
    actor_id: str | None = None,
    action: str | None = None,
    target_type: str | None = None,
    target_id: str | None = None,
    started_at: datetime | None = None,
    ended_at: datetime | None = None,
    _: UserModel = Depends(require_permission(PermissionCode.AUDIT_READ)),
    session: AsyncSession = Depends(get_session_instance),
):
    if started_at and ended_at and started_at > ended_at:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="开始时间不能晚于结束时间")
    async with session.begin():
        items, total = await IamRepo(session).get_audit_logs(
            page=page,
            size=size,
            actor_id=actor_id,
            action=action,
            target_type=target_type,
            target_id=target_id,
            started_at=started_at,
            ended_at=ended_at,
        )
    return {"items": items, "total": total}


@router.get("/me/sessions", response_model=list[AuthSessionSchema], summary="查询当前用户登录会话")
async def list_my_sessions(
    current_user: UserModel = Depends(get_current_user),
    token_claims: dict = Depends(get_access_token_claims),
    session: AsyncSession = Depends(get_session_instance),
):
    async with session.begin():
        sessions = await AuthSessionRepo(session).list_user_sessions(current_user.id)
    current_session_id = None if token_claims.get("legacy") else str(token_claims.get("sid"))
    return [_serialize_auth_session(item, current_session_id) for item in sessions]


@router.delete("/me/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT, summary="撤销当前用户的一台登录设备")
async def revoke_my_session(
    session_id: str,
    current_user: UserModel = Depends(get_current_user),
    session: AsyncSession = Depends(get_session_instance),
):
    async with session.begin():
        revoked = await AuthSessionService(session).revoke_session(
            user_id=current_user.id,
            session_id=session_id,
            reason="self_revoke",
            actor_id=current_user.id,
        )
    if not revoked:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="会话不存在或已失效")


@router.post("/invitations", response_model=IamInvitationSchema, status_code=status.HTTP_201_CREATED, summary="创建带初始角色的持久化邀请")
async def create_invitation(
    payload: IamInvitationCreateSchema,
    background_tasks: BackgroundTasks,
    current_admin: UserModel = Depends(require_permission(PermissionCode.USER_INVITE)),
    session: AsyncSession = Depends(get_session_instance),
):
    try:
        async with session.begin():
            invitation, invite_code = await InvitationService(session).create_invitation(
                email=str(payload.email),
                username=payload.username,
                department_id=payload.department_id,
                role_code=payload.role_code,
                department_scope_ids=payload.department_scope_ids,
                expires_at=payload.expires_at,
                reason=payload.reason,
                actor_id=current_admin.id,
            )
    except InvitationValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except InvitationConflict as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    background_tasks.add_task(
        send_invite_email_task,
        email=invitation.email,
        invite_code=invite_code,
        username=invitation.username,
    )
    return _serialize_invitation(invitation)


@router.get("/users", response_model=IamUserListSchema, summary="分页查询用户")
async def list_users(
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
    department_id: str | None = None,
    include_descendants: bool = False,
    role_code: str | None = None,
    keyword: str | None = Query(default=None, max_length=100),
    user_status: UserStatus | None = Query(default=None, alias="status"),
    _: UserModel = Depends(require_permission(PermissionCode.USER_READ)),
    session: AsyncSession = Depends(get_session_instance),
):
    async with session.begin():
        users, total = await UserRepo(session).get_iam_user_list(
            page=page,
            size=size,
            department_id=department_id,
            include_descendants=include_descendants,
            role_code=role_code,
            keyword=keyword,
            user_status=user_status,
        )
        roles_by_user = await IamRepo(session).get_active_roles_by_user_ids(
            [user.id for user in users]
        )
    return {
        "users": [
            _serialize_user(
                user,
                [user_role.role.code for user_role in roles_by_user.get(user.id, [])],
            )
            for user in users
        ],
        "total": total,
    }


@router.get("/users/{user_id}", response_model=IamUserSchema, summary="获取用户详情")
async def get_user(
    user_id: str,
    _: UserModel = Depends(require_permission(PermissionCode.USER_READ)),
    session: AsyncSession = Depends(get_session_instance),
):
    async with session.begin():
        user = await _get_user_or_404(user_id, UserRepo(session))
        user_roles = await IamRepo(session).get_active_user_roles(user.id)
    return _serialize_user(user, [user_role.role.code for user_role in user_roles])


@router.get("/users/{user_id}/roles", response_model=list[UserRoleSchema], summary="查询用户角色授予明细")
async def get_user_roles(
    user_id: str,
    _: UserModel = Depends(require_permission(PermissionCode.ROLE_READ)),
    session: AsyncSession = Depends(get_session_instance),
):
    async with session.begin():
        user = await _get_user_or_404(user_id, UserRepo(session))
        user_roles = await IamRepo(session).get_active_user_roles(user.id)
    return [_serialize_user_role(user_role) for user_role in user_roles]


@router.patch("/users/{user_id}", response_model=IamUserSchema, summary="修改用户基础资料")
async def update_user(
    user_id: str,
    payload: UserProfileUpdateSchema,
    current_admin: UserModel = Depends(require_permission(PermissionCode.USER_UPDATE)),
    session: AsyncSession = Depends(get_session_instance),
):
    try:
        async with session.begin():
            user = await _get_user_or_404(user_id, UserRepo(session))
            service = OrganizationService(session)
            user = await service.update_user_profile(
                user=user,
                data=payload.model_dump(exclude_unset=True),
                actor_id=current_admin.id,
            )
            user_roles = await IamRepo(session).get_active_user_roles(user.id)
    except OrganizationValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    return _serialize_user(user, [user_role.role.code for user_role in user_roles])


@router.patch("/users/{user_id}/status", response_model=IamUserSchema, summary="停用、启用或标记用户离职")
async def update_user_status(
    user_id: str,
    payload: IamUserStatusUpdateSchema,
    current_admin: UserModel = Depends(require_permission(PermissionCode.USER_DISABLE)),
    session: AsyncSession = Depends(get_session_instance),
):
    if user_id == current_admin.id:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="不能修改当前登录管理员的状态")
    try:
        async with session.begin():
            user = await _get_user_or_404(user_id, UserRepo(session))
            service = OrganizationService(session)
            user = await service.update_user_status(
                user=user,
                user_status=payload.status,
                actor_id=current_admin.id,
            )
            user_roles = await IamRepo(session).get_active_user_roles(user.id)
    except OrganizationValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    return _serialize_user(user, [user_role.role.code for user_role in user_roles])


@router.post("/users/{user_id}/reset-password", status_code=status.HTTP_204_NO_CONTENT, summary="管理员重置用户密码")
async def reset_user_password(
    user_id: str,
    payload: UserPasswordResetSchema,
    current_admin: UserModel = Depends(require_permission(PermissionCode.USER_RESET_PASSWORD)),
    session: AsyncSession = Depends(get_session_instance),
):
    if user_id == current_admin.id:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="请通过个人密码修改流程更新当前管理员密码")
    try:
        async with session.begin():
            user = await _get_user_or_404(user_id, UserRepo(session))
            await AuthSessionService(session).reset_password(
                user=user,
                new_password=payload.new_password,
                actor_id=current_admin.id,
            )
    except PasswordPolicyError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc


@router.post("/users/{user_id}/sessions/revoke", status_code=status.HTTP_204_NO_CONTENT, summary="撤销用户全部有效会话")
async def revoke_user_sessions(
    user_id: str,
    current_admin: UserModel = Depends(require_permission(PermissionCode.USER_SESSION_REVOKE)),
    session: AsyncSession = Depends(get_session_instance),
):
    if user_id == current_admin.id:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="不能撤销当前管理员自身全部会话")
    async with session.begin():
        await _get_user_or_404(user_id, UserRepo(session))
        await AuthSessionService(session).revoke_user_sessions(
            user_id=user_id,
            reason="admin_revoke",
            actor_id=current_admin.id,
        )


@router.post("/users/{user_id}/roles", response_model=UserRoleSchema, status_code=status.HTTP_201_CREATED, summary="授予用户角色")
async def grant_user_role(
    user_id: str,
    payload: UserRoleGrantSchema,
    current_admin: UserModel = Depends(require_permission(PermissionCode.ROLE_ASSIGN)),
    session: AsyncSession = Depends(get_session_instance),
):
    try:
        async with session.begin():
            user = await _get_user_or_404(user_id, UserRepo(session))
            user_role = await RoleAssignmentService(session).grant_role(
                user=user,
                role_code=payload.role_code,
                department_ids=payload.department_ids,
                expires_at=payload.expires_at,
                reason=payload.reason,
                actor_id=current_admin.id,
            )
    except RoleAssignmentValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except RoleAssignmentConflict as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except IntegrityError as exc:
        # user_roles 的部分唯一索引仍是并发重复授予时的最终防线。
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="用户已拥有该角色") from exc
    return _serialize_user_role(user_role)


@router.delete("/user-roles/{user_role_id}", response_model=UserRoleSchema, summary="撤销用户角色")
async def revoke_user_role(
    user_role_id: str,
    payload: UserRoleRevokeSchema,
    current_admin: UserModel = Depends(require_permission(PermissionCode.ROLE_ASSIGN)),
    session: AsyncSession = Depends(get_session_instance),
):
    try:
        async with session.begin():
            iam_repo = IamRepo(session)
            user_role = await iam_repo.get_user_role_by_id(user_role_id)
            if not user_role:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户角色不存在")
            if user_role.user_id == current_admin.id:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="不能撤销当前管理员自身角色")
            user = await _get_user_or_404(user_role.user_id, UserRepo(session))
            user_role = await RoleAssignmentService(session).revoke_role(
                user_role=user_role,
                user=user,
                actor_id=current_admin.id,
                reason=payload.reason,
            )
    except RoleAssignmentValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except RoleAssignmentConflict as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return _serialize_user_role(user_role)


@router.put("/user-roles/{user_role_id}/scopes/departments", response_model=UserRoleSchema, summary="替换角色的部门范围")
async def replace_user_role_department_scopes(
    user_role_id: str,
    payload: UserRoleScopeReplaceSchema,
    current_admin: UserModel = Depends(require_permission(PermissionCode.ROLE_ASSIGN)),
    session: AsyncSession = Depends(get_session_instance),
):
    try:
        async with session.begin():
            iam_repo = IamRepo(session)
            user_role = await iam_repo.get_user_role_by_id(user_role_id)
            if not user_role:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户角色不存在")
            user = await _get_user_or_404(user_role.user_id, UserRepo(session))
            user_role = await RoleAssignmentService(session).replace_department_scopes(
                user_role=user_role,
                user=user,
                department_ids=payload.department_ids,
                actor_id=current_admin.id,
                reason=payload.reason,
            )
    except RoleAssignmentValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except RoleAssignmentConflict as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return _serialize_user_role(user_role)


@router.get("/departments", response_model=list[IamDepartmentSchema], summary="查询部门")
async def list_departments(
    include_archived: bool = False,
    _: UserModel = Depends(get_current_user),
    session: AsyncSession = Depends(get_session_instance),
):
    async with session.begin():
        return await DepartmentRepo(session).get_department_list(
            include_archived=include_archived
        )


@router.get(
    "/departments/tree",
    response_model=list[IamDepartmentTreeNodeSchema],
    summary="查询部门树",
)
async def get_department_tree(
    include_archived: bool = False,
    _: UserModel = Depends(require_permission(PermissionCode.DEPARTMENT_READ)),
    session: AsyncSession = Depends(get_session_instance),
):
    async with session.begin():
        departments = await DepartmentRepo(session).get_department_list(
            include_archived=include_archived
        )

    nodes = {
        department.id: {
            "id": department.id,
            "code": department.code,
            "name": department.name,
            "description": department.description,
            "status": department.status,
            "parent_id": department.parent_id,
            "archived_at": department.archived_at,
            "children": [],
        }
        for department in departments
    }
    roots = []
    for department in departments:
        node = nodes[department.id]
        if department.parent_id and department.parent_id in nodes:
            nodes[department.parent_id]["children"].append(node)
        else:
            roots.append(node)
    return roots


@router.get(
    "/departments/{department_id}/summary",
    response_model=DepartmentSummarySchema,
    summary="查询部门工作台摘要",
)
async def get_department_summary(
    department_id: str,
    _: UserModel = Depends(require_permission(PermissionCode.DEPARTMENT_READ)),
    session: AsyncSession = Depends(get_session_instance),
):
    async with session.begin():
        department_repo = DepartmentRepo(session)
        await _get_department_or_404(department_id, department_repo)
        return await department_repo.get_department_summary(department_id)


@router.get("/departments/{department_id}", response_model=IamDepartmentSchema, summary="获取部门详情")
async def get_department(
    department_id: str,
    _: UserModel = Depends(require_permission(PermissionCode.DEPARTMENT_READ)),
    session: AsyncSession = Depends(get_session_instance),
):
    async with session.begin():
        return await _get_department_or_404(department_id, DepartmentRepo(session))


@router.post("/departments", response_model=IamDepartmentSchema, status_code=status.HTTP_201_CREATED, summary="创建部门")
async def create_department(
    payload: DepartmentCreateSchema,
    current_admin: UserModel = Depends(require_permission(PermissionCode.DEPARTMENT_CREATE)),
    session: AsyncSession = Depends(get_session_instance),
):
    try:
        async with session.begin():
            return await OrganizationService(session).create_department(
                data=payload.model_dump(), actor_id=current_admin.id
            )
    except OrganizationValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc


@router.patch("/departments/{department_id}", response_model=IamDepartmentSchema, summary="修改部门")
async def update_department(
    department_id: str,
    payload: DepartmentUpdateSchema,
    current_admin: UserModel = Depends(require_permission(PermissionCode.DEPARTMENT_UPDATE)),
    session: AsyncSession = Depends(get_session_instance),
):
    try:
        async with session.begin():
            department = await _get_department_or_404(department_id, DepartmentRepo(session))
            return await OrganizationService(session).update_department(
                department=department,
                data=payload.model_dump(exclude_unset=True),
                actor_id=current_admin.id,
            )
    except OrganizationValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc


@router.get("/departments/{department_id}/dependencies", response_model=DepartmentDependencySchema, summary="查询部门归档依赖")
async def get_department_dependencies(
    department_id: str,
    _: UserModel = Depends(require_permission(PermissionCode.DEPARTMENT_ARCHIVE)),
    session: AsyncSession = Depends(get_session_instance),
):
    async with session.begin():
        department_repo = DepartmentRepo(session)
        await _get_department_or_404(department_id, department_repo)
        return await department_repo.get_archive_dependencies(department_id)


@router.delete("/departments/{department_id}", response_model=IamDepartmentSchema, summary="归档部门")
async def archive_department(
    department_id: str,
    current_admin: UserModel = Depends(require_permission(PermissionCode.DEPARTMENT_ARCHIVE)),
    session: AsyncSession = Depends(get_session_instance),
):
    try:
        async with session.begin():
            department = await _get_department_or_404(department_id, DepartmentRepo(session))
            return await OrganizationService(session).archive_department(
                department=department,
                actor_id=current_admin.id,
            )
    except DepartmentArchiveConflict as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"message": str(exc), "dependencies": exc.dependencies},
        ) from exc
