"""add assistant conversation tables

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a8
Create Date: 2026-07-13 12:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c3d4e5f6a7b8"
down_revision: Union[str, Sequence[str], None] = "b2c3d4e5f6a8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """创建招聘助手的业务会话和消息表。"""

    op.create_table(
        "assistant_conversations",
        sa.Column("user_id", sa.String(length=100), nullable=False),
        sa.Column("title", sa.String(length=100), nullable=False),
        sa.Column(
            "status",
            sa.Enum("active", "archived", "deleted", name="assistantconversationstatusenum"),
            nullable=False,
        ),
        sa.Column("last_message_at", sa.DateTime(), nullable=False),
        sa.Column("id", sa.String(length=100), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_assistant_conversations_user_id_users"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_assistant_conversations")),
    )
    op.create_index(op.f("ix_assistant_conversations_user_id"), "assistant_conversations", ["user_id"], unique=False)
    op.create_index(op.f("ix_assistant_conversations_status"), "assistant_conversations", ["status"], unique=False)
    op.create_index(op.f("ix_assistant_conversations_last_message_at"), "assistant_conversations", ["last_message_at"], unique=False)
    op.create_index(
        "ix_assistant_conversation_user_status_last_message",
        "assistant_conversations",
        ["user_id", "status", "last_message_at"],
        unique=False,
    )

    op.create_table(
        "assistant_messages",
        sa.Column("conversation_id", sa.String(length=100), nullable=False),
        sa.Column(
            "role",
            sa.Enum("user", "assistant", "tool", name="assistantmessageroleenum"),
            nullable=False,
        ),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("tool_name", sa.String(length=100), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=True),
        sa.Column("id", sa.String(length=100), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["assistant_conversations.id"],
            name=op.f("fk_assistant_messages_conversation_id_assistant_conversations"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_assistant_messages")),
    )
    op.create_index(op.f("ix_assistant_messages_conversation_id"), "assistant_messages", ["conversation_id"], unique=False)
    op.create_index(op.f("ix_assistant_messages_role"), "assistant_messages", ["role"], unique=False)
    op.create_index(
        "ix_assistant_message_conversation_created",
        "assistant_messages",
        ["conversation_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    """删除招聘助手会话表。"""

    op.drop_index("ix_assistant_message_conversation_created", table_name="assistant_messages")
    op.drop_index(op.f("ix_assistant_messages_role"), table_name="assistant_messages")
    op.drop_index(op.f("ix_assistant_messages_conversation_id"), table_name="assistant_messages")
    op.drop_table("assistant_messages")
    op.drop_index("ix_assistant_conversation_user_status_last_message", table_name="assistant_conversations")
    op.drop_index(op.f("ix_assistant_conversations_last_message_at"), table_name="assistant_conversations")
    op.drop_index(op.f("ix_assistant_conversations_status"), table_name="assistant_conversations")
    op.drop_index(op.f("ix_assistant_conversations_user_id"), table_name="assistant_conversations")
    op.drop_table("assistant_conversations")
    op.execute("DROP TYPE assistantmessageroleenum")
    op.execute("DROP TYPE assistantconversationstatusenum")
