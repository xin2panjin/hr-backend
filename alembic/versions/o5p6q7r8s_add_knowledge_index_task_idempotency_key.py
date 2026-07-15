"""add knowledge index task idempotency key

Revision ID: o5p6q7r8s
Revises: n4o5p6q7r8s
Create Date: 2026-07-14
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "o5p6q7r8s"
down_revision = "n4o5p6q7r8s"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """为历史任务补齐唯一幂等键，再建立非空和唯一约束。"""

    op.add_column(
        "knowledge_index_tasks",
        sa.Column("idempotency_key", sa.String(length=64), nullable=True),
    )
    # 当前项目的主键为短 UUID；以 legacy 前缀保留历史任务的唯一性，
    # 不伪造其内容哈希语义，也不会影响新任务使用正式幂等键。
    op.execute(
        "UPDATE knowledge_index_tasks "
        "SET idempotency_key = CONCAT('legacy:', id) "
        "WHERE idempotency_key IS NULL"
    )
    op.alter_column("knowledge_index_tasks", "idempotency_key", nullable=False)
    op.create_unique_constraint(
        "uq_knowledge_index_tasks_idempotency_key",
        "knowledge_index_tasks",
        ["idempotency_key"],
    )


def downgrade() -> None:
    """移除任务幂等键约束与字段。"""

    op.drop_constraint(
        "uq_knowledge_index_tasks_idempotency_key",
        "knowledge_index_tasks",
        type_="unique",
    )
    op.drop_column("knowledge_index_tasks", "idempotency_key")
