"""add candidate agent events

Revision ID: b2c3d4e5f6a8
Revises: 80d68ac7591f
Create Date: 2026-07-12 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "b2c3d4e5f6a8"
down_revision: Union[str, Sequence[str], None] = "80d68ac7591f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "candidate_agent_events",
        sa.Column("thread_id", sa.String(length=255), nullable=True),
        sa.Column("candidate_id", sa.String(length=100), nullable=True),
        sa.Column("position_id", sa.String(length=100), nullable=True),
        sa.Column("interviewer_id", sa.String(length=100), nullable=True),
        sa.Column("event_type", sa.String(length=64), nullable=True),
        sa.Column("node_name", sa.String(length=128), nullable=False),
        sa.Column("action_type", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("stage_before", sa.String(length=64), nullable=True),
        sa.Column("stage_after", sa.String(length=64), nullable=True),
        sa.Column("route_decision", sa.String(length=128), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("input_summary", sa.JSON(), nullable=True),
        sa.Column("output_summary", sa.JSON(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("id", sa.String(length=100), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_candidate_agent_events")),
    )
    op.create_index(
        op.f("ix_candidate_agent_events_action_type"),
        "candidate_agent_events",
        ["action_type"],
        unique=False,
    )
    op.create_index(
        op.f("ix_candidate_agent_events_candidate_id"),
        "candidate_agent_events",
        ["candidate_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_candidate_agent_events_event_type"),
        "candidate_agent_events",
        ["event_type"],
        unique=False,
    )
    op.create_index(
        op.f("ix_candidate_agent_events_interviewer_id"),
        "candidate_agent_events",
        ["interviewer_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_candidate_agent_events_node_name"),
        "candidate_agent_events",
        ["node_name"],
        unique=False,
    )
    op.create_index(
        op.f("ix_candidate_agent_events_position_id"),
        "candidate_agent_events",
        ["position_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_candidate_agent_events_status"),
        "candidate_agent_events",
        ["status"],
        unique=False,
    )
    op.create_index(
        op.f("ix_candidate_agent_events_thread_id"),
        "candidate_agent_events",
        ["thread_id"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        op.f("ix_candidate_agent_events_thread_id"),
        table_name="candidate_agent_events",
    )
    op.drop_index(
        op.f("ix_candidate_agent_events_status"),
        table_name="candidate_agent_events",
    )
    op.drop_index(
        op.f("ix_candidate_agent_events_position_id"),
        table_name="candidate_agent_events",
    )
    op.drop_index(
        op.f("ix_candidate_agent_events_node_name"),
        table_name="candidate_agent_events",
    )
    op.drop_index(
        op.f("ix_candidate_agent_events_interviewer_id"),
        table_name="candidate_agent_events",
    )
    op.drop_index(
        op.f("ix_candidate_agent_events_event_type"),
        table_name="candidate_agent_events",
    )
    op.drop_index(
        op.f("ix_candidate_agent_events_candidate_id"),
        table_name="candidate_agent_events",
    )
    op.drop_index(
        op.f("ix_candidate_agent_events_action_type"),
        table_name="candidate_agent_events",
    )
    op.drop_table("candidate_agent_events")
