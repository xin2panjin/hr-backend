"""add IAM RBAC tables

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-07-14 00:00:00.000000

"""
from datetime import datetime
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "d4e5f6a7b8c9"
down_revision: Union[str, Sequence[str], None] = "c3d4e5f6a7b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


PERMISSIONS = (
    "user.read",
    "user.invite",
    "user.update",
    "user.disable",
    "user.reset_password",
    "user.session.revoke",
    "role.read",
    "role.assign",
    "department.read",
    "department.create",
    "department.update",
    "department.archive",
    "position.read",
    "position.create",
    "position.delete",
    "candidate.read",
    "candidate.create",
    "candidate.update_status",
    "candidate.read_ai_score",
    "resume.upload",
    "resume.parse",
    "talent_search.query",
    "assistant.use",
)

ROLE_DEFINITIONS = {
    "ROLE_SYSTEM_ADMIN": ("系统管理员", "管理系统、用户、角色与全部业务数据"),
    "ROLE_HR_ADMIN": ("招聘管理员", "管理招聘业务、招聘用户和招聘配置"),
    "ROLE_HR_RECRUITER": ("招聘专员", "在负责部门范围内执行招聘工作"),
    "ROLE_HIRING_MANAGER": ("用人部门负责人", "管理本人创建职位及其候选人"),
    "ROLE_EMPLOYEE": ("普通员工", "维护个人资料并上传、解析本人简历"),
}

ROLE_PERMISSIONS = {
    "ROLE_SYSTEM_ADMIN": set(PERMISSIONS),
    "ROLE_HR_ADMIN": {
        "user.read", "user.invite", "user.update", "user.disable",
        "role.read", "role.assign", "department.read", "position.read",
        "position.create", "position.delete", "candidate.read", "candidate.create",
        "candidate.update_status", "candidate.read_ai_score", "resume.upload",
        "resume.parse", "talent_search.query", "assistant.use",
    },
    "ROLE_HR_RECRUITER": {
        "position.read", "position.create", "candidate.read", "candidate.create",
        "candidate.update_status", "candidate.read_ai_score", "resume.upload",
        "resume.parse", "talent_search.query", "assistant.use",
    },
    "ROLE_HIRING_MANAGER": {
        "position.read", "position.create", "position.delete", "candidate.read",
        "candidate.create", "candidate.update_status", "candidate.read_ai_score",
        "resume.upload", "resume.parse", "talent_search.query",
    },
    "ROLE_EMPLOYEE": {"resume.upload", "resume.parse"},
}


def upgrade() -> None:
    """创建 RBAC 表，并安全回填已有超管和 HR。"""

    now = datetime.utcnow()
    scope_type = sa.Enum("DEPARTMENT", name="scopetypeenum")

    op.create_table(
        "roles",
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_system", sa.Boolean(), nullable=False),
        sa.Column("id", sa.String(length=100), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_roles")),
        sa.UniqueConstraint("code", name=op.f("uq_roles_code")),
    )
    op.create_index(op.f("ix_roles_code"), "roles", ["code"], unique=False)

    op.create_table(
        "permissions",
        sa.Column("code", sa.String(length=100), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("resource", sa.String(length=64), nullable=False),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("id", sa.String(length=100), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_permissions")),
        sa.UniqueConstraint("code", name=op.f("uq_permissions_code")),
    )
    op.create_index(op.f("ix_permissions_code"), "permissions", ["code"], unique=False)

    op.create_table(
        "role_permissions",
        sa.Column("role_id", sa.String(length=100), nullable=False),
        sa.Column("permission_id", sa.String(length=100), nullable=False),
        sa.ForeignKeyConstraint(["permission_id"], ["permissions.id"], ondelete="CASCADE", name=op.f("fk_role_permissions_permission_id_permissions")),
        sa.ForeignKeyConstraint(["role_id"], ["roles.id"], ondelete="CASCADE", name=op.f("fk_role_permissions_role_id_roles")),
        sa.PrimaryKeyConstraint("role_id", "permission_id", name=op.f("pk_role_permissions")),
    )

    op.create_table(
        "user_roles",
        sa.Column("user_id", sa.String(length=100), nullable=False),
        sa.Column("role_id", sa.String(length=100), nullable=False),
        sa.Column("assigned_by", sa.String(length=100), nullable=True),
        sa.Column("assigned_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.Column("revoke_reason", sa.String(length=255), nullable=True),
        sa.Column("id", sa.String(length=100), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["assigned_by"], ["users.id"], name=op.f("fk_user_roles_assigned_by_users")),
        sa.ForeignKeyConstraint(["role_id"], ["roles.id"], name=op.f("fk_user_roles_role_id_roles")),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_user_roles_user_id_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_user_roles")),
    )
    op.create_index(op.f("ix_user_roles_role_id"), "user_roles", ["role_id"], unique=False)
    op.create_index(op.f("ix_user_roles_user_id"), "user_roles", ["user_id"], unique=False)
    op.create_index(
        "uq_user_roles_active_user_role",
        "user_roles",
        ["user_id", "role_id"],
        unique=True,
        postgresql_where=sa.text("revoked_at IS NULL"),
    )

    op.create_table(
        "user_role_scopes",
        sa.Column("user_role_id", sa.String(length=100), nullable=False),
        sa.Column("scope_type", scope_type, nullable=False),
        sa.Column("department_id", sa.String(length=100), nullable=True),
        sa.Column("id", sa.String(length=100), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["department_id"], ["departments.id"], name=op.f("fk_user_role_scopes_department_id_departments")),
        sa.ForeignKeyConstraint(["user_role_id"], ["user_roles.id"], ondelete="CASCADE", name=op.f("fk_user_role_scopes_user_role_id_user_roles")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_user_role_scopes")),
    )
    op.create_index(op.f("ix_user_role_scopes_user_role_id"), "user_role_scopes", ["user_role_id"], unique=False)

    op.create_table(
        "audit_logs",
        sa.Column("actor_id", sa.String(length=100), nullable=True),
        sa.Column("action", sa.String(length=100), nullable=False),
        sa.Column("target_type", sa.String(length=100), nullable=False),
        sa.Column("target_id", sa.String(length=100), nullable=True),
        sa.Column("before_data", sa.JSON(), nullable=True),
        sa.Column("after_data", sa.JSON(), nullable=True),
        sa.Column("request_id", sa.String(length=100), nullable=True),
        sa.Column("ip_address", sa.String(length=64), nullable=True),
        sa.Column("id", sa.String(length=100), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"], name=op.f("fk_audit_logs_actor_id_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_logs")),
    )
    op.create_index(op.f("ix_audit_logs_action"), "audit_logs", ["action"], unique=False)
    op.create_index(op.f("ix_audit_logs_actor_id"), "audit_logs", ["actor_id"], unique=False)
    op.create_index(op.f("ix_audit_logs_request_id"), "audit_logs", ["request_id"], unique=False)
    op.create_index(op.f("ix_audit_logs_target_id"), "audit_logs", ["target_id"], unique=False)
    op.create_index(op.f("ix_audit_logs_target_type"), "audit_logs", ["target_type"], unique=False)

    role_rows = [
        {
            "id": code,
            "code": code,
            "name": name,
            "description": description,
            "is_system": True,
            "created_at": now,
            "updated_at": now,
        }
        for code, (name, description) in ROLE_DEFINITIONS.items()
    ]
    permission_rows = []
    for code in PERMISSIONS:
        resource, action = code.split(".", maxsplit=1)
        permission_rows.append(
            {
                "id": code,
                "code": code,
                "name": code,
                "resource": resource,
                "action": action,
                "description": None,
                "created_at": now,
                "updated_at": now,
            }
        )
    role_permission_rows = [
        {"role_id": role_code, "permission_id": permission_code}
        for role_code, permission_codes in ROLE_PERMISSIONS.items()
        for permission_code in sorted(permission_codes)
    ]

    role_table = sa.table(
        "roles",
        sa.column("id", sa.String(100)),
        sa.column("code", sa.String(64)),
        sa.column("name", sa.String(100)),
        sa.column("description", sa.Text()),
        sa.column("is_system", sa.Boolean()),
        sa.column("created_at", sa.DateTime()),
        sa.column("updated_at", sa.DateTime()),
    )
    permission_table = sa.table(
        "permissions",
        sa.column("id", sa.String(100)),
        sa.column("code", sa.String(100)),
        sa.column("name", sa.String(100)),
        sa.column("resource", sa.String(64)),
        sa.column("action", sa.String(64)),
        sa.column("description", sa.Text()),
        sa.column("created_at", sa.DateTime()),
        sa.column("updated_at", sa.DateTime()),
    )
    role_permission_table = sa.table(
        "role_permissions",
        sa.column("role_id", sa.String(100)),
        sa.column("permission_id", sa.String(100)),
    )
    op.bulk_insert(role_table, role_rows)
    op.bulk_insert(permission_table, permission_rows)
    op.bulk_insert(role_permission_table, role_permission_rows)

    op.execute(
        """
        INSERT INTO user_roles (
            id, user_id, role_id, assigned_by, assigned_at, expires_at,
            revoked_at, revoke_reason, created_at, updated_at
        )
        SELECT md5('bootstrap-system-admin:' || id), id, 'ROLE_SYSTEM_ADMIN', NULL,
               CURRENT_TIMESTAMP, NULL, NULL, NULL, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
        FROM users
        WHERE is_superuser = true
        """
    )
    op.execute(
        """
        INSERT INTO user_roles (
            id, user_id, role_id, assigned_by, assigned_at, expires_at,
            revoked_at, revoke_reason, created_at, updated_at
        )
        SELECT md5('bootstrap-recruiter:' || id), id, 'ROLE_HR_RECRUITER', NULL,
               CURRENT_TIMESTAMP, NULL, NULL, NULL, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
        FROM users
        WHERE is_hr = true AND is_superuser = false
        """
    )
    op.execute(
        """
        INSERT INTO user_role_scopes (
            id, user_role_id, scope_type, department_id, created_at, updated_at
        )
        SELECT md5('bootstrap-recruiter-scope:' || relation.user_id || ':' || relation.department_id),
               md5('bootstrap-recruiter:' || relation.user_id),
               'DEPARTMENT', relation.department_id, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
        FROM hr_managed_departments AS relation
        JOIN users AS user_info ON user_info.id = relation.user_id
        WHERE user_info.is_hr = true AND user_info.is_superuser = false
        """
    )


def downgrade() -> None:
    """移除 RBAC 表。"""

    op.drop_index(op.f("ix_audit_logs_target_type"), table_name="audit_logs")
    op.drop_index(op.f("ix_audit_logs_target_id"), table_name="audit_logs")
    op.drop_index(op.f("ix_audit_logs_request_id"), table_name="audit_logs")
    op.drop_index(op.f("ix_audit_logs_actor_id"), table_name="audit_logs")
    op.drop_index(op.f("ix_audit_logs_action"), table_name="audit_logs")
    op.drop_table("audit_logs")

    op.drop_index(op.f("ix_user_role_scopes_user_role_id"), table_name="user_role_scopes")
    op.drop_table("user_role_scopes")
    sa.Enum(name="scopetypeenum").drop(op.get_bind(), checkfirst=True)

    op.drop_index("uq_user_roles_active_user_role", table_name="user_roles")
    op.drop_index(op.f("ix_user_roles_user_id"), table_name="user_roles")
    op.drop_index(op.f("ix_user_roles_role_id"), table_name="user_roles")
    op.drop_table("user_roles")
    op.drop_table("role_permissions")

    op.drop_index(op.f("ix_permissions_code"), table_name="permissions")
    op.drop_table("permissions")
    op.drop_index(op.f("ix_roles_code"), table_name="roles")
    op.drop_table("roles")
