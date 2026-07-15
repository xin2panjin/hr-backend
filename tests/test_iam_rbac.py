from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

from sqlalchemy.orm import configure_mappers

from iam.permissions import (
    ALL_PERMISSIONS,
    PermissionCode,
    RoleCode,
    SYSTEM_ROLE_DEFINITIONS,
)
from models import Base


def test_system_role_definitions_only_reference_declared_permissions():
    declared_permissions = set(PermissionCode)

    assert set(ALL_PERMISSIONS) == declared_permissions
    assert {definition.code for definition in SYSTEM_ROLE_DEFINITIONS} == set(RoleCode)
    for definition in SYSTEM_ROLE_DEFINITIONS:
        assert definition.permissions <= declared_permissions


def test_iam_models_are_registered_in_sqlalchemy_metadata():
    configure_mappers()
    table_names = set(Base.metadata.tables)

    assert {
        "roles",
        "permissions",
        "role_permissions",
        "user_roles",
        "user_role_scopes",
        "audit_logs",
        "auth_sessions",
    } <= table_names


def test_iam_migration_follows_current_alembic_head():
    migration_path = (
        Path(__file__).resolve().parents[1]
        / "alembic/versions/d4e5f6a7b8c9_add_iam_rbac_tables.py"
    )
    spec = spec_from_file_location("iam_rbac_migration", migration_path)
    assert spec and spec.loader
    migration = module_from_spec(spec)
    spec.loader.exec_module(migration)

    assert migration.revision == "d4e5f6a7b8c9"
    assert migration.down_revision == "c3d4e5f6a7b8"
    assert set(migration.PERMISSIONS) == {
        permission.value
        for permission in PermissionCode
        if permission
        not in {
            PermissionCode.AUDIT_READ,
            PermissionCode.ROLE_UPDATE_PERMISSIONS,
                PermissionCode.KNOWLEDGE_DOCUMENT_MANAGE,
                PermissionCode.CANDIDATE_COMMUNICATION_USE,
        }
    }
    assert set(migration.ROLE_DEFINITIONS) == {role.value for role in RoleCode}
    assert set(migration.ROLE_PERMISSIONS["ROLE_SYSTEM_ADMIN"]) == set(migration.PERMISSIONS)


def test_organization_lifecycle_migration_follows_iam_rbac_migration():
    migration_path = (
        Path(__file__).resolve().parents[1]
        / "alembic/versions/e5f6a7b8c9d0_add_organization_lifecycle_fields.py"
    )
    spec = spec_from_file_location("organization_lifecycle_migration", migration_path)
    assert spec and spec.loader
    migration = module_from_spec(spec)
    spec.loader.exec_module(migration)

    assert migration.revision == "e5f6a7b8c9d0"
    assert migration.down_revision == "d4e5f6a7b8c9"


def test_persistent_invitation_migration_follows_organization_lifecycle_migration():
    migration_path = (
        Path(__file__).resolve().parents[1]
        / "alembic/versions/f6a7b8c9d0e1_add_persistent_invitations.py"
    )
    spec = spec_from_file_location("persistent_invitation_migration", migration_path)
    assert spec and spec.loader
    migration = module_from_spec(spec)
    spec.loader.exec_module(migration)

    assert migration.revision == "f6a7b8c9d0e1"
    assert migration.down_revision == "e5f6a7b8c9d0"


def test_auth_session_migration_follows_persistent_invitation_migration():
    migration_path = (
        Path(__file__).resolve().parents[1]
        / "alembic/versions/g7b8c9d0e1f2_add_auth_sessions.py"
    )
    spec = spec_from_file_location("auth_session_migration", migration_path)
    assert spec and spec.loader
    migration = module_from_spec(spec)
    spec.loader.exec_module(migration)

    assert migration.revision == "g7b8c9d0e1f2"
    assert migration.down_revision == "f6a7b8c9d0e1"


def test_audit_read_permission_migration_follows_auth_session_migration():
    migration_path = (
        Path(__file__).resolve().parents[1]
        / "alembic/versions/h8c9d0e1f2a3_add_audit_read_permission.py"
    )
    spec = spec_from_file_location("audit_permission_migration", migration_path)
    assert spec and spec.loader
    migration = module_from_spec(spec)
    spec.loader.exec_module(migration)

    assert migration.revision == "h8c9d0e1f2a3"
    assert migration.down_revision == "g7b8c9d0e1f2"


def test_formal_code_migration_follows_oauth_state_migration():
    migration_path = (
        Path(__file__).resolve().parents[1]
        / "alembic/versions/j0e1f2a3b4c5_formalize_iam_role_and_department_codes.py"
    )
    spec = spec_from_file_location("formal_codes_migration", migration_path)
    assert spec and spec.loader
    migration = module_from_spec(spec)
    spec.loader.exec_module(migration)

    assert migration.revision == "j0e1f2a3b4c5"
    assert migration.down_revision == "i9d0e1f2a3b4"
    assert migration.ROLE_CODE_RENAMES == {
        "system_admin": RoleCode.SYSTEM_ADMIN.value,
        "hr_admin": RoleCode.HR_ADMIN.value,
        "recruiter": RoleCode.RECRUITER.value,
        "hiring_manager": RoleCode.HIRING_MANAGER.value,
        "employee": RoleCode.EMPLOYEE.value,
    }


def test_oauth_state_migration_follows_audit_permission_migration():
    migration_path = (
        Path(__file__).resolve().parents[1]
        / "alembic/versions/i9d0e1f2a3b4_add_oauth_states.py"
    )
    spec = spec_from_file_location("oauth_state_migration", migration_path)
    assert spec and spec.loader
    migration = module_from_spec(spec)
    spec.loader.exec_module(migration)

    assert migration.revision == "i9d0e1f2a3b4"
    assert migration.down_revision == "h8c9d0e1f2a3"


def test_role_permission_management_migration_follows_legacy_field_removal():
    migration_path = (
        Path(__file__).resolve().parents[1]
        / "alembic/versions/l2g3h4i5j6k7_add_role_permission_management.py"
    )
    spec = spec_from_file_location("role_permission_management_migration", migration_path)
    assert spec and spec.loader
    migration = module_from_spec(spec)
    spec.loader.exec_module(migration)

    assert migration.revision == "l2g3h4i5j6k7"
    assert migration.down_revision == "k1f2a3b4c5d6"
