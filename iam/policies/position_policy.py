"""职位资源的数据范围策略。"""

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import false
from iam.permissions import RoleCode
from models.iam import ScopeTypeEnum


class PositionScopeType(StrEnum):
    ALL = "ALL"
    MANAGED_DEPARTMENTS = "MANAGED_DEPARTMENTS"
    OWN_POSITIONS = "OWN_POSITIONS"
    NONE = "NONE"


@dataclass(frozen=True)
class PositionAccessScope:
    type: PositionScopeType
    department_ids: tuple[str, ...] = ()
    creator_id: str | None = None


class PositionPolicy:
    """统一职位列表、创建、删除及候选人创建时的职位访问规则。"""

    @classmethod
    def resolve_scope(cls, actor: Any) -> PositionAccessScope:
        user_roles = getattr(actor, "iam_roles", []) or []
        if any(
            user_role.role.code in {RoleCode.SYSTEM_ADMIN.value, RoleCode.HR_ADMIN.value}
            for user_role in user_roles
        ):
            return PositionAccessScope(PositionScopeType.ALL)

        department_ids = tuple(sorted({
            str(scope.department_id)
            for user_role in user_roles
            if user_role.role.code == RoleCode.RECRUITER.value
            for scope in user_role.scopes
            if scope.scope_type == ScopeTypeEnum.DEPARTMENT and scope.department_id
        }))
        if department_ids:
            return PositionAccessScope(PositionScopeType.MANAGED_DEPARTMENTS, department_ids=department_ids)

        if not any(user_role.role.code == RoleCode.HIRING_MANAGER.value for user_role in user_roles):
            return PositionAccessScope(PositionScopeType.NONE)

        actor_id = getattr(actor, "id", None)
        if not actor_id:
            return PositionAccessScope(PositionScopeType.NONE)
        return PositionAccessScope(
            PositionScopeType.OWN_POSITIONS,
            creator_id=str(actor_id),
        )

    @classmethod
    def can_read(cls, actor: Any, position: Any) -> bool:
        scope = cls.resolve_scope(actor)
        if scope.type == PositionScopeType.ALL:
            return True
        if scope.type == PositionScopeType.NONE:
            return False
        if scope.type == PositionScopeType.MANAGED_DEPARTMENTS:
            return cls._resource_id(position, "department_id", "department") in scope.department_ids
        return cls._resource_id(position, "creator_id", "creator") == scope.creator_id

    @classmethod
    def ensure_can_create(cls, actor: Any, department_id: str | None) -> None:
        scope = cls.resolve_scope(actor)
        allowed = False
        if scope.type == PositionScopeType.ALL:
            allowed = True
        elif scope.type == PositionScopeType.MANAGED_DEPARTMENTS:
            allowed = department_id in scope.department_ids
        elif scope.type == PositionScopeType.OWN_POSITIONS:
            allowed = department_id == cls._resource_id(actor, "department_id", "department")

        if not allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="没有权限在该部门创建职位",
            )

    @classmethod
    def ensure_can_delete(cls, actor: Any, position: Any) -> None:
        if not cls.can_read(actor, position):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="没有权限删除该职位",
            )

    @classmethod
    def ensure_can_use_for_candidate(cls, actor: Any, position: Any) -> None:
        if not cls.can_read(actor, position):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="没有权限在该职位下创建候选人",
            )

    @classmethod
    def apply_sql_scope(cls, stmt, scope: PositionAccessScope, position_model):
        """为职位 SQL 查询附加统一的数据范围条件。"""

        if scope.type == PositionScopeType.ALL:
            return stmt
        if scope.type == PositionScopeType.MANAGED_DEPARTMENTS:
            return stmt.where(position_model.department_id.in_(scope.department_ids))
        if scope.type == PositionScopeType.OWN_POSITIONS:
            return stmt.where(position_model.creator_id == scope.creator_id)
        return stmt.where(false())

    @staticmethod
    def _resource_id(resource: Any, id_attr: str, relation_attr: str) -> str | None:
        value = getattr(resource, id_attr, None)
        if value:
            return str(value)
        relation = getattr(resource, relation_attr, None)
        relation_id = getattr(relation, "id", None)
        return str(relation_id) if relation_id else None
