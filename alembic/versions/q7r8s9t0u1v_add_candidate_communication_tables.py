"""add candidate communication tables

Revision ID: q7r8s9t0u1v
Revises: p6q7r8s9t0u
Create Date: 2026-07-15 15:00:00.000000
"""

from datetime import datetime

from alembic import op
import sqlalchemy as sa


revision = "q7r8s9t0u1v"
down_revision = "p6q7r8s9t0u"
branch_labels = None
depends_on = None


def upgrade() -> None:
    message_sender = sa.Enum("candidate", "hr", name="candidatemessagesenderenum")
    outbox_status = sa.Enum("pending", "processing", "completed", "failed", name="candidateinsightoutboxstatusenum")
    task_status = sa.Enum("pending", "in_progress", "completed", "cancelled", name="candidatefollowuptaskstatusenum")
    task_priority = sa.Enum("high", "medium", "low", name="candidatetaskpriorityenum")

    op.create_table(
        "candidate_conversations",
        sa.Column("candidate_id", sa.String(100), nullable=False),
        sa.Column("owner_id", sa.String(100), nullable=True),
        sa.Column("last_message_at", sa.DateTime(), nullable=False),
        sa.Column("id", sa.String(100), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["candidate_id"], ["candidates.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"), sa.UniqueConstraint("candidate_id"),
    )
    op.create_index("ix_candidate_conversations_candidate_id", "candidate_conversations", ["candidate_id"])
    op.create_index("ix_candidate_conversations_owner_id", "candidate_conversations", ["owner_id"])
    op.create_index("ix_candidate_conversations_last_message_at", "candidate_conversations", ["last_message_at"])

    op.create_table(
        "candidate_conversation_messages",
        sa.Column("conversation_id", sa.String(100), nullable=False),
        sa.Column("sender_type", message_sender, nullable=False), sa.Column("sender_user_id", sa.String(100), nullable=True),
        sa.Column("content", sa.Text(), nullable=False), sa.Column("id", sa.String(100), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False), sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["conversation_id"], ["candidate_conversations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["sender_user_id"], ["users.id"], ondelete="SET NULL"), sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_candidate_conversation_messages_conversation_id", "candidate_conversation_messages", ["conversation_id"])

    op.create_table(
        "candidate_conversation_read_states",
        sa.Column("conversation_id", sa.String(100), nullable=False), sa.Column("user_id", sa.String(100), nullable=False),
        sa.Column("last_read_at", sa.DateTime(), nullable=False), sa.Column("id", sa.String(100), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False), sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["conversation_id"], ["candidate_conversations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"), sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("conversation_id", "user_id", name="uq_candidate_conversation_read_state"),
    )
    op.create_index("ix_candidate_conversation_read_states_conversation_id", "candidate_conversation_read_states", ["conversation_id"])
    op.create_index("ix_candidate_conversation_read_states_user_id", "candidate_conversation_read_states", ["user_id"])

    op.create_table(
        "candidate_conversation_insights",
        sa.Column("conversation_id", sa.String(100), nullable=False), sa.Column("source_message_id", sa.String(100), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False), sa.Column("stage", sa.String(50)), sa.Column("intent", sa.String(100)),
        sa.Column("confirmed_facts", sa.JSON()), sa.Column("candidate_requests", sa.JSON()), sa.Column("hr_commitments", sa.JSON()),
        sa.Column("risks", sa.JSON()), sa.Column("next_step", sa.Text()), sa.Column("evidence", sa.JSON()),
        sa.Column("id", sa.String(100), nullable=False), sa.Column("created_at", sa.DateTime(), nullable=False), sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["conversation_id"], ["candidate_conversations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_message_id"], ["candidate_conversation_messages.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"), sa.UniqueConstraint("source_message_id"),
    )
    op.create_index("ix_candidate_conversation_insights_conversation_id", "candidate_conversation_insights", ["conversation_id"])

    op.create_table(
        "candidate_insight_outbox",
        sa.Column("source_message_id", sa.String(100), nullable=False), sa.Column("status", outbox_status, nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False), sa.Column("last_error", sa.Text()), sa.Column("processed_at", sa.DateTime()),
        sa.Column("id", sa.String(100), nullable=False), sa.Column("created_at", sa.DateTime(), nullable=False), sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["source_message_id"], ["candidate_conversation_messages.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"), sa.UniqueConstraint("source_message_id"),
    )
    op.create_index("ix_candidate_insight_outbox_status", "candidate_insight_outbox", ["status"])

    op.create_table(
        "candidate_followup_tasks",
        sa.Column("conversation_id", sa.String(100), nullable=False), sa.Column("candidate_id", sa.String(100), nullable=False),
        sa.Column("assignee_id", sa.String(100)), sa.Column("source_outbox_id", sa.String(100)), sa.Column("title", sa.String(200), nullable=False),
        sa.Column("task_type", sa.String(50), nullable=False), sa.Column("priority", task_priority, nullable=False),
        sa.Column("status", task_status, nullable=False), sa.Column("due_at", sa.DateTime()), sa.Column("evidence", sa.JSON()),
        sa.Column("id", sa.String(100), nullable=False), sa.Column("created_at", sa.DateTime(), nullable=False), sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["conversation_id"], ["candidate_conversations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["candidate_id"], ["candidates.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["assignee_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["source_outbox_id"], ["candidate_insight_outbox.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"), sa.UniqueConstraint("source_outbox_id"),
    )
    for column in ("conversation_id", "candidate_id", "assignee_id", "status"):
        op.create_index(f"ix_candidate_followup_tasks_{column}", "candidate_followup_tasks", [column])

    op.create_table(
        "candidate_followup_task_notes",
        sa.Column("task_id", sa.String(100), nullable=False), sa.Column("author_id", sa.String(100)), sa.Column("content", sa.Text(), nullable=False),
        sa.Column("id", sa.String(100), nullable=False), sa.Column("created_at", sa.DateTime(), nullable=False), sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["task_id"], ["candidate_followup_tasks.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["author_id"], ["users.id"], ondelete="SET NULL"), sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_candidate_followup_task_notes_task_id", "candidate_followup_task_notes", ["task_id"])

    permissions = sa.table("permissions", sa.column("id", sa.String()), sa.column("code", sa.String()), sa.column("name", sa.String()), sa.column("resource", sa.String()), sa.column("action", sa.String()), sa.column("description", sa.String()), sa.column("created_at", sa.DateTime()), sa.column("updated_at", sa.DateTime()))
    now = datetime.utcnow()
    op.bulk_insert(permissions, [{"id": "candidate.communication.use", "code": "candidate.communication.use", "name": "使用候选人沟通", "resource": "candidate", "action": "communication_use", "description": "查看候选人会话、洞察和待办", "created_at": now, "updated_at": now}])
    op.execute("INSERT INTO role_permissions (role_id, permission_id) SELECT id, 'candidate.communication.use' FROM roles WHERE code IN ('ROLE_SYSTEM_ADMIN', 'ROLE_HR_ADMIN', 'ROLE_HR_RECRUITER', 'ROLE_HIRING_MANAGER')")


def downgrade() -> None:
    op.execute("DELETE FROM role_permissions WHERE permission_id = 'candidate.communication.use'")
    op.execute("DELETE FROM permissions WHERE id = 'candidate.communication.use'")
    for table in ("candidate_followup_task_notes", "candidate_followup_tasks", "candidate_insight_outbox", "candidate_conversation_insights", "candidate_conversation_read_states", "candidate_conversation_messages", "candidate_conversations"):
        op.drop_table(table)
    for enum_name in ("candidatetaskpriorityenum", "candidatefollowuptaskstatusenum", "candidateinsightoutboxstatusenum", "candidatemessagesenderenum"):
        sa.Enum(name=enum_name).drop(op.get_bind(), checkfirst=True)
