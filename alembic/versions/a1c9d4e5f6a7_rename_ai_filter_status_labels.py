"""rename ai filter status labels

Revision ID: a1c9d4e5f6a7
Revises: 7e311707bf3b
Create Date: 2026-06-26 23:45:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "a1c9d4e5f6a7"
down_revision: Union[str, Sequence[str], None] = "7e311707bf3b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


NEW_VALUES = (
    "已投递",
    "AI筛选未通过",
    "AI筛选通过",
    "待面试",
    "拒绝面试",
    "面试通过",
    "面试未通过",
    "已入职",
    "已拒绝",
)

OLD_VALUES = (
    "已投递",
    "AI筛选失败",
    "AI筛选成功",
    "待面试",
    "拒绝面试",
    "面试通过",
    "面试未通过",
    "已入职",
    "已拒绝",
)


def _enum_values(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("ALTER TYPE candidatestatusenum RENAME TO candidatestatusenum_old")
    op.execute(f"CREATE TYPE candidatestatusenum AS ENUM ({_enum_values(NEW_VALUES)})")
    op.execute(
        """
        ALTER TABLE candidates
        ALTER COLUMN status TYPE candidatestatusenum
        USING (
            CASE status::text
                WHEN 'AI筛选失败' THEN 'AI筛选未通过'
                WHEN 'AI筛选成功' THEN 'AI筛选通过'
                ELSE status::text
            END
        )::candidatestatusenum
        """
    )
    op.execute("DROP TYPE candidatestatusenum_old")


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("ALTER TYPE candidatestatusenum RENAME TO candidatestatusenum_new")
    op.execute(f"CREATE TYPE candidatestatusenum AS ENUM ({_enum_values(OLD_VALUES)})")
    op.execute(
        """
        ALTER TABLE candidates
        ALTER COLUMN status TYPE candidatestatusenum
        USING (
            CASE status::text
                WHEN 'AI筛选未通过' THEN 'AI筛选失败'
                WHEN 'AI筛选通过' THEN 'AI筛选成功'
                ELSE status::text
            END
        )::candidatestatusenum
        """
    )
    op.execute("DROP TYPE candidatestatusenum_new")
