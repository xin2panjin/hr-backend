"""add organization lifecycle fields

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-07-14 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "e5f6a7b8c9d0"
down_revision: Union[str, Sequence[str], None] = "d4e5f6a7b8c9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """补齐用户授权版本与部门生命周期字段，并回填历史部门编码。"""

    department_status = sa.Enum("ACTIVE", "ARCHIVED", name="departmentstatus")
    department_status.create(op.get_bind(), checkfirst=True)

    op.add_column(
        "users",
        sa.Column("authz_version", sa.Integer(), nullable=False, server_default="1"),
    )
    op.add_column("users", sa.Column("last_login_at", sa.DateTime(), nullable=True))
    op.add_column("users", sa.Column("disabled_at", sa.DateTime(), nullable=True))
    op.add_column("users", sa.Column("disabled_by", sa.String(length=100), nullable=True))
    op.create_foreign_key(
        op.f("fk_users_disabled_by_users"), "users", "users", ["disabled_by"], ["id"]
    )
    op.alter_column("users", "authz_version", server_default=None)

    # 先允许 NULL，再按创建顺序回填正式部门码，最后收紧为非空唯一字段。
    op.add_column("departments", sa.Column("code", sa.String(length=64), nullable=True))
    op.add_column(
        "departments",
        sa.Column("status", department_status, nullable=False, server_default="ACTIVE"),
    )
    op.add_column("departments", sa.Column("parent_id", sa.String(length=100), nullable=True))
    op.add_column("departments", sa.Column("archived_at", sa.DateTime(), nullable=True))
    op.add_column("departments", sa.Column("archived_by", sa.String(length=100), nullable=True))
    op.execute(
        """
        WITH numbered_departments AS (
            SELECT id, ROW_NUMBER() OVER (ORDER BY created_at, id) AS sequence_no
            FROM departments
            WHERE code IS NULL
        )
        UPDATE departments AS department
        SET code = 'DEPT-' || LPAD(numbered_departments.sequence_no::text, 6, '0')
        FROM numbered_departments
        WHERE department.id = numbered_departments.id
        """
    )
    op.alter_column("departments", "code", nullable=False)
    op.alter_column("departments", "status", server_default=None)
    op.create_index(op.f("ix_departments_code"), "departments", ["code"], unique=True)
    op.create_foreign_key(
        op.f("fk_departments_parent_id_departments"),
        "departments",
        "departments",
        ["parent_id"],
        ["id"],
    )
    op.create_foreign_key(
        op.f("fk_departments_archived_by_users"),
        "departments",
        "users",
        ["archived_by"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint(op.f("fk_departments_archived_by_users"), "departments", type_="foreignkey")
    op.drop_constraint(op.f("fk_departments_parent_id_departments"), "departments", type_="foreignkey")
    op.drop_index(op.f("ix_departments_code"), table_name="departments")
    op.drop_column("departments", "archived_by")
    op.drop_column("departments", "archived_at")
    op.drop_column("departments", "parent_id")
    op.drop_column("departments", "status")
    op.drop_column("departments", "code")

    op.drop_constraint(op.f("fk_users_disabled_by_users"), "users", type_="foreignkey")
    op.drop_column("users", "disabled_by")
    op.drop_column("users", "disabled_at")
    op.drop_column("users", "last_login_at")
    op.drop_column("users", "authz_version")

    sa.Enum(name="departmentstatus").drop(op.get_bind(), checkfirst=True)
