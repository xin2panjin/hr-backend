"""add persistent invitations

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-07-14 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f6a7b8c9d0e1"
down_revision: Union[str, Sequence[str], None] = "e5f6a7b8c9d0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "invitations",
        sa.Column("email", sa.String(length=100), nullable=False),
        sa.Column("department_id", sa.String(length=100), nullable=False),
        sa.Column("role_id", sa.String(length=100), nullable=False),
        sa.Column("department_scope_ids", sa.JSON(), nullable=False),
        sa.Column("invite_code_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("invited_by", sa.String(length=100), nullable=True),
        sa.Column("reason", sa.String(length=255), nullable=True),
        sa.Column("used_at", sa.DateTime(), nullable=True),
        sa.Column("used_by_user_id", sa.String(length=100), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(), nullable=True),
        sa.Column("cancelled_by", sa.String(length=100), nullable=True),
        sa.Column("id", sa.String(length=100), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["department_id"], ["departments.id"], name=op.f("fk_invitations_department_id_departments")),
        sa.ForeignKeyConstraint(["role_id"], ["roles.id"], name=op.f("fk_invitations_role_id_roles")),
        sa.ForeignKeyConstraint(["invited_by"], ["users.id"], name=op.f("fk_invitations_invited_by_users")),
        sa.ForeignKeyConstraint(["used_by_user_id"], ["users.id"], name=op.f("fk_invitations_used_by_user_id_users")),
        sa.ForeignKeyConstraint(["cancelled_by"], ["users.id"], name=op.f("fk_invitations_cancelled_by_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_invitations")),
        sa.UniqueConstraint("invite_code_hash", name=op.f("uq_invitations_invite_code_hash")),
    )
    op.create_index(op.f("ix_invitations_email"), "invitations", ["email"], unique=False)
    op.create_index(
        "uq_invitations_pending_email",
        "invitations",
        ["email"],
        unique=True,
        postgresql_where=sa.text("used_at IS NULL AND cancelled_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_invitations_pending_email", table_name="invitations")
    op.drop_index(op.f("ix_invitations_email"), table_name="invitations")
    op.drop_table("invitations")
