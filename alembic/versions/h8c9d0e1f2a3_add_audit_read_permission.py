"""add audit read permission

Revision ID: h8c9d0e1f2a3
Revises: g7b8c9d0e1f2
Create Date: 2026-07-14 00:00:00.000000

"""
from datetime import datetime
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "h8c9d0e1f2a3"
down_revision: Union[str, Sequence[str], None] = "g7b8c9d0e1f2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    permissions = sa.table(
        "permissions",
        sa.column("id", sa.String()),
        sa.column("code", sa.String()),
        sa.column("name", sa.String()),
        sa.column("resource", sa.String()),
        sa.column("action", sa.String()),
        sa.column("description", sa.String()),
        sa.column("created_at", sa.DateTime()),
        sa.column("updated_at", sa.DateTime()),
    )
    role_permissions = sa.table(
        "role_permissions",
        sa.column("role_id", sa.String()),
        sa.column("permission_id", sa.String()),
    )
    now = datetime.utcnow()
    op.bulk_insert(permissions, [{
        "id": "audit.read", "code": "audit.read", "name": "查看审计日志",
        "resource": "audit", "action": "read", "description": "查看 IAM 敏感操作审计日志",
        "created_at": now, "updated_at": now,
    }])
    op.execute(
        """
        INSERT INTO role_permissions (role_id, permission_id)
        SELECT id, 'audit.read'
        FROM roles
        WHERE name = '系统管理员'
        """
    )


def downgrade() -> None:
    op.execute("DELETE FROM role_permissions WHERE permission_id = 'audit.read'")
    op.execute("DELETE FROM permissions WHERE id = 'audit.read'")
