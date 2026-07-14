"""remove legacy user authorization fields

Revision ID: k1f2a3b4c5d6
Revises: j0e1f2a3b4c5
Create Date: 2026-07-14 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


revision: str = "k1f2a3b4c5d6"
down_revision: Union[str, Sequence[str], None] = "j0e1f2a3b4c5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """RBAC 已成为唯一授权来源，删除旧布尔字段和 HR 关联表。"""

    op.drop_table("hr_managed_departments")
    op.drop_column("users", "is_hr")
    op.drop_column("users", "is_superuser")


def downgrade() -> None:
    # 不恢复已废弃的兼容授权模型。
    pass
