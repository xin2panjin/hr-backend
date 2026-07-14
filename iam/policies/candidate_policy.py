"""候选人资源的数据范围策略。"""

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import false

from models.positions import PositionModel
from models.iam import ScopeTypeEnum
from iam.permissions import RoleCode


class CandidateScopeType(StrEnum):
    """候选人资源支持的数据范围类型。"""

    ALL = "ALL"
    MANAGED_DEPARTMENTS = "MANAGED_DEPARTMENTS"
    OWN_POSITIONS = "OWN_POSITIONS"
    NONE = "NONE"


@dataclass(frozen=True)
class CandidateAccessScope:
    """调用人对候选人资源拥有的有效数据范围。"""

    type: CandidateScopeType
    department_ids: tuple[str, ...] = ()
    position_creator_id: str | None = None


class CandidatePolicy:
    """统一候选人列表、详情、写操作和检索的授权规则。"""

    _DENY_MILVUS_FILTER = 'candidate_id == "__no_candidate_access__"'

    @classmethod
    def resolve_scope(cls, actor: Any) -> CandidateAccessScope:
        """从当前有效 RBAC 角色和范围解析候选人数据范围。"""

        user_roles = getattr(actor, "iam_roles", []) or []
        if any(
            user_role.role.code in {RoleCode.SYSTEM_ADMIN.value, RoleCode.HR_ADMIN.value}
            for user_role in user_roles
        ):
            return CandidateAccessScope(CandidateScopeType.ALL)

        department_ids = tuple(sorted({
            str(scope.department_id)
            for user_role in user_roles
            if user_role.role.code == RoleCode.RECRUITER.value
            for scope in user_role.scopes
            if scope.scope_type == ScopeTypeEnum.DEPARTMENT and scope.department_id
        }))
        if department_ids:
            return CandidateAccessScope(CandidateScopeType.MANAGED_DEPARTMENTS, department_ids=department_ids)

        if not any(user_role.role.code == RoleCode.HIRING_MANAGER.value for user_role in user_roles):
            return CandidateAccessScope(CandidateScopeType.NONE)

        actor_id = getattr(actor, "id", None)
        if not actor_id:
            return CandidateAccessScope(CandidateScopeType.NONE)
        return CandidateAccessScope(
            CandidateScopeType.OWN_POSITIONS,
            position_creator_id=str(actor_id),
        )

    @classmethod
    def can_read(cls, actor: Any, candidate: Any) -> bool:
        """判断调用人是否可读取指定候选人。"""

        scope = cls.resolve_scope(actor)
        if scope.type == CandidateScopeType.ALL:
            return True
        if scope.type == CandidateScopeType.NONE:
            return False

        position = getattr(candidate, "position", None)
        if not position:
            return False

        if scope.type == CandidateScopeType.MANAGED_DEPARTMENTS:
            department_id = cls._resource_id(position, "department_id", "department")
            return department_id in scope.department_ids

        position_creator_id = cls._resource_id(position, "creator_id", "creator")
        return position_creator_id == scope.position_creator_id

    @classmethod
    def ensure_can_read(cls, actor: Any, candidate: Any) -> None:
        """读取候选人失败时抛出统一的资源级权限错误。"""

        if not cls.can_read(actor, candidate):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="没有权限查看该候选人",
            )

    @classmethod
    def ensure_can_update_status(cls, actor: Any, candidate: Any) -> None:
        """状态流转属于候选人写操作，沿用同一资源范围规则。"""

        if not cls.can_read(actor, candidate):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="没有权限更新该候选人的状态",
            )

    @classmethod
    def apply_sql_scope(cls, stmt, scope: CandidateAccessScope):
        """为候选人 SQL 查询附加统一的数据范围条件。"""

        if scope.type == CandidateScopeType.ALL:
            return stmt
        if scope.type == CandidateScopeType.MANAGED_DEPARTMENTS:
            return stmt.join(PositionModel).where(
                PositionModel.department_id.in_(scope.department_ids)
            )
        if scope.type == CandidateScopeType.OWN_POSITIONS:
            return stmt.join(PositionModel).where(
                PositionModel.creator_id == scope.position_creator_id
            )
        return stmt.where(false())

    @classmethod
    def build_milvus_filter(
        cls,
        *,
        actor: Any,
        position_id: str | None,
        status: Any | None,
    ) -> str:
        """构造与 SQL 范围语义一致的 Milvus 标量过滤表达式。"""

        scope = cls.resolve_scope(actor)
        filters: list[str] = []

        if scope.type == CandidateScopeType.MANAGED_DEPARTMENTS:
            quoted_ids = ", ".join(f'"{department_id}"' for department_id in scope.department_ids)
            filters.append(f"department_id in [{quoted_ids}]")
        elif scope.type == CandidateScopeType.OWN_POSITIONS:
            filters.append(f'creator_id == "{scope.position_creator_id}"')
        elif scope.type == CandidateScopeType.NONE:
            filters.append(cls._DENY_MILVUS_FILTER)

        if position_id:
            filters.append(f'position_id == "{position_id}"')

        if status:
            filters.append(f'status == "{status.value}"')

        return " and ".join(filters)

    @staticmethod
    def _resource_id(resource: Any, id_attr: str, relation_attr: str) -> str | None:
        """同时兼容 ORM 外键字段和测试中的关联对象。"""

        value = getattr(resource, id_attr, None)
        if value:
            return str(value)

        relation = getattr(resource, relation_attr, None)
        relation_id = getattr(relation, "id", None)
        return str(relation_id) if relation_id else None
