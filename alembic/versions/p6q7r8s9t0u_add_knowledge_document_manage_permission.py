"""add knowledge document manage permission

Revision ID: p6q7r8s9t0u
Revises: o5p6q7r8s
"""

from datetime import datetime

from alembic import op
import sqlalchemy as sa


revision = "p6q7r8s9t0u"
down_revision = "o5p6q7r8s"
branch_labels = None
depends_on = None

PERMISSION_CODE = "knowledge.document_manage"


def upgrade() -> None:
    """注册制度文档管理权限，并只授予系统/招聘管理员。"""

    permissions = sa.table(
        "permissions",
        sa.column("id", sa.String()), sa.column("code", sa.String()),
        sa.column("name", sa.String()), sa.column("resource", sa.String()),
        sa.column("action", sa.String()), sa.column("description", sa.String()),
        sa.column("created_at", sa.DateTime()), sa.column("updated_at", sa.DateTime()),
    )
    now = datetime.utcnow()
    op.bulk_insert(permissions, [{
        "id": PERMISSION_CODE, "code": PERMISSION_CODE,
        "name": "管理制度知识库", "resource": "knowledge", "action": "document_manage",
        "description": "上传、重建、归档企业制度文档并查看索引状态",
        "created_at": now, "updated_at": now,
    }])
    op.execute(
        "INSERT INTO role_permissions (role_id, permission_id) "
        "SELECT id, 'knowledge.document_manage' FROM roles "
        "WHERE code IN ('ROLE_SYSTEM_ADMIN', 'ROLE_HR_ADMIN')"
    )


def downgrade() -> None:
    op.execute("DELETE FROM role_permissions WHERE permission_id = 'knowledge.document_manage'")
    op.execute("DELETE FROM permissions WHERE id = 'knowledge.document_manage'")
