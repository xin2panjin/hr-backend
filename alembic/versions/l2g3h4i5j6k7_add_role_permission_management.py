"""add role permission management capability

Revision ID: l2g3h4i5j6k7
Revises: k1f2a3b4c5d6
Create Date: 2026-07-14 00:00:00.000000
"""

from datetime import datetime
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "l2g3h4i5j6k7"
down_revision: Union[str, Sequence[str], None] = "k1f2a3b4c5d6"
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
    op.bulk_insert(
        permissions,
        [{
            "id": "role.update_permissions",
            "code": "role.update_permissions",
            "name": "编辑角色权限",
            "resource": "role",
            "action": "update_permissions",
            "description": "调整既有权限项在角色中的勾选关系",
            "created_at": now,
            "updated_at": now,
        }],
    )
    op.execute(
        """
        INSERT INTO role_permissions (role_id, permission_id)
        SELECT id, 'role.update_permissions'
        FROM roles
        WHERE code = 'ROLE_SYSTEM_ADMIN'
        """
    )


def downgrade() -> None:
    op.execute("DELETE FROM role_permissions WHERE permission_id = 'role.update_permissions'")
    op.execute("DELETE FROM permissions WHERE id = 'role.update_permissions'")
