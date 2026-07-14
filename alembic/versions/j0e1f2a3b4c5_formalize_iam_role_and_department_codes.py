"""formalize IAM role and department codes

Revision ID: j0e1f2a3b4c5
Revises: i9d0e1f2a3b4
Create Date: 2026-07-14 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


revision: str = "j0e1f2a3b4c5"
down_revision: Union[str, Sequence[str], None] = "i9d0e1f2a3b4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


ROLE_CODE_RENAMES = {
    "system_admin": "ROLE_SYSTEM_ADMIN",
    "hr_admin": "ROLE_HR_ADMIN",
    "recruiter": "ROLE_HR_RECRUITER",
    "hiring_manager": "ROLE_HIRING_MANAGER",
    "employee": "ROLE_EMPLOYEE",
}


def upgrade() -> None:
    """原地收敛开发数据，不保留临时代码或运行时兼容分支。"""

    for temporary_code, formal_code in ROLE_CODE_RENAMES.items():
        op.execute(
            "UPDATE roles SET code = "
            f"'{formal_code}' WHERE code = '{temporary_code}'"
        )

    # 部门码未被外键引用；开发阶段按创建顺序重新编号，确保没有 legacy 或自由格式残留。
    op.execute("UPDATE departments SET code = 'DEPT-MIGRATE-' || id")
    op.execute(
        """
        WITH numbered_departments AS (
            SELECT id, ROW_NUMBER() OVER (ORDER BY created_at, id) AS sequence_no
            FROM departments
        )
        UPDATE departments AS department
        SET code = 'DEPT-' || LPAD(numbered_departments.sequence_no::text, 6, '0')
        FROM numbered_departments
        WHERE department.id = numbered_departments.id
        """
    )


def downgrade() -> None:
    # 开发期直接收敛的正式码不恢复为临时代码。
    pass
