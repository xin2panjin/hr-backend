"""add candidate insight available at

Revision ID: r8s9t0u1v2w
Revises: q7r8s9t0u1v
Create Date: 2026-07-15 16:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "r8s9t0u1v2w"
down_revision = "q7r8s9t0u1v"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """为已有 outbox 补齐五分钟静默窗口，并为新事件提供领取时间。"""

    op.add_column("candidate_insight_outbox", sa.Column("available_at", sa.DateTime(), nullable=True))
    op.execute(
        "UPDATE candidate_insight_outbox "
        "SET available_at = created_at + INTERVAL '5 minutes' "
        "WHERE available_at IS NULL"
    )
    op.alter_column("candidate_insight_outbox", "available_at", nullable=False)
    op.create_index("ix_candidate_insight_outbox_available_at", "candidate_insight_outbox", ["available_at"])


def downgrade() -> None:
    op.drop_index("ix_candidate_insight_outbox_available_at", table_name="candidate_insight_outbox")
    op.drop_column("candidate_insight_outbox", "available_at")
