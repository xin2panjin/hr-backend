"""简历资源与解析任务的归属策略。"""

from typing import Any

from fastapi import HTTPException, status
from iam.permissions import RoleCode


class ResumePolicy:
    """第一阶段的最小简历权限规则。

    简历解析发生在候选人创建之前，尚不存在可用于 HR 部门范围判断的职位。
    因此当前仅允许上传者本人或超级管理员解析和读取任务结果；后续可在
    RBAC 与候选人归属完整后扩展为更细的数据范围。
    """

    @classmethod
    def can_manage_resume(cls, actor: Any, resume: Any) -> bool:
        if cls._has_global_access(actor):
            return True
        return bool(
            getattr(actor, "id", None)
            and getattr(actor, "id", None) == getattr(resume, "uploader_id", None)
        )

    @classmethod
    def ensure_can_parse(cls, actor: Any, resume: Any) -> None:
        cls.ensure_can_manage_resume(actor, resume, detail="没有权限解析该简历")

    @classmethod
    def ensure_can_manage_resume(
        cls,
        actor: Any,
        resume: Any,
        *,
        detail: str = "没有权限操作该简历",
    ) -> None:
        if not cls.can_manage_resume(actor, resume):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=detail,
            )

    @classmethod
    def ensure_can_read_task(cls, actor: Any, owner_id: str) -> None:
        if cls._has_global_access(actor):
            return
        if getattr(actor, "id", None) == owner_id:
            return
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="没有权限查看该简历解析任务",
        )

    @staticmethod
    def _has_global_access(actor: Any) -> bool:
        return any(
            user_role.role.code in {RoleCode.SYSTEM_ADMIN.value, RoleCode.HR_ADMIN.value}
            for user_role in getattr(actor, "iam_roles", []) or []
        )
