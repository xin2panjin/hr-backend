"""add invitation username and case insensitive user login

Revision ID: m3n4o5p6q7r8
Revises: l2g3h4i5j6k7
Create Date: 2026-07-14 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "m3n4o5p6q7r8"
down_revision: Union[str, Sequence[str], None] = "l2g3h4i5j6k7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 正式用户名统一小写，规避 PostgreSQL 默认唯一约束的大小写敏感漏洞。
    op.execute("UPDATE users SET username = lower(username)")
    op.create_index("uq_users_username_ci", "users", [sa.text("lower(username)")], unique=True)

    # 对本地已有邀请生成仅用于升级的占位用户名；新邀请由 API 强制传入用户名。
    op.add_column("invitations", sa.Column("username", sa.String(length=50), nullable=True))
    op.execute("UPDATE invitations SET username = 'legacy-' || lower(id) WHERE username IS NULL")
    op.alter_column("invitations", "username", nullable=False)
    op.create_index(op.f("ix_invitations_username"), "invitations", ["username"], unique=False)
    op.create_index(
        "uq_invitations_pending_username_ci",
        "invitations",
        [sa.text("lower(username)")],
        unique=True,
        postgresql_where=sa.text("used_at IS NULL AND cancelled_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_invitations_pending_username_ci", table_name="invitations")
    op.drop_index(op.f("ix_invitations_username"), table_name="invitations")
    op.drop_column("invitations", "username")
    op.drop_index("uq_users_username_ci", table_name="users")
