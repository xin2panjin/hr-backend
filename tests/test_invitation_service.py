from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from iam.services.invitation_service import InvitationService, InvitationValidationError
from iam.services.role_assignment_service import RoleAssignmentValidationError
from models.iam import RoleModel
from models.user import DepartmentStatus, UserStatus


class FakeSession:
    def __init__(self):
        self.added = []
        self.flush_count = 0

    def add(self, item):
        self.added.append(item)

    async def flush(self):
        self.flush_count += 1
        for item in self.added:
            if getattr(item, "id", None) is None:
                item.id = f"generated-{self.flush_count}"


class FakeIamRepo:
    def __init__(self, role, *, unresolved=None, invitation=None, has_invitation=False):
        self.role = role
        self.unresolved = unresolved
        self.invitation = invitation
        self.has_invitation = has_invitation

    async def get_pending_invitation_by_email(self, _):
        return None

    async def get_unresolved_invitation_by_email(self, _):
        return self.unresolved

    async def get_unresolved_invitation_by_username(self, _):
        return None

    async def get_unresolved_invitation_by_username(self, _):
        return None

    async def get_role_by_code(self, role_code):
        return self.role if self.role.code == role_code else None

    async def get_invitation_for_registration(self, **_):
        return self.invitation

    async def has_invitation_for_email(self, _):
        return self.has_invitation


class FakeUserRepo:
    def __init__(self, user=None):
        self.user = user

    async def get_by_email(self, _):
        return self.user

    async def get_by_username(self, _):
        return None

    async def get_by_username(self, _):
        return None

    async def create_user(self, data):
        self.user = SimpleNamespace(
            id="user-1",
            status=UserStatus.ACTIVE,
            authz_version=1,
            **data,
        )
        return self.user


class FakeDepartmentRepo:
    def __init__(self, department):
        self.department = department

    async def get_by_id(self, department_id):
        return self.department if department_id == self.department.id else None


class FakeRoleAssignmentService:
    async def validate_role_scope(self, **kwargs):
        if kwargs["role_code"] == "ROLE_HR_RECRUITER" and not kwargs["department_ids"]:
            raise RoleAssignmentValidationError("招聘专员必须配置至少一个负责部门")
        return list(dict.fromkeys(kwargs["department_ids"]))

    async def grant_role(self, **kwargs):
        self.grant_kwargs = kwargs
        return SimpleNamespace(id="user-role-1")


def build_service(*, role_code="ROLE_HR_RECRUITER", unresolved=None, invitation=None):
    session = FakeSession()
    role = RoleModel(id=f"role-{role_code}", code=role_code, name=role_code, is_system=True)
    service = InvitationService(session)
    service.iam_repo = FakeIamRepo(role, unresolved=unresolved, invitation=invitation)
    service.user_repo = FakeUserRepo()
    service.department_repo = FakeDepartmentRepo(
        SimpleNamespace(id="dept-1", status=DepartmentStatus.ACTIVE)
    )
    service.role_assignment_service = FakeRoleAssignmentService()
    return service


def test_invite_code_hash_is_case_insensitive_for_email_and_secret_bound():
    first = InvitationService.hash_invite_code("User@Example.com", "secret-code")
    second = InvitationService.hash_invite_code("user@example.com", "secret-code")
    third = InvitationService.hash_invite_code("user@example.com", "other-code")

    assert first == second
    assert first != third
    assert len(first) == 64


@pytest.mark.asyncio
async def test_create_invitation_requires_recruiter_scope():
    service = build_service()

    with pytest.raises(RoleAssignmentValidationError, match="至少一个"):
        await service.create_invitation(
            email="new@example.com",
            username="new-user",
            department_id="dept-1",
            role_code="ROLE_HR_RECRUITER",
            department_scope_ids=[],
            expires_at=None,
            reason="招聘入职",
            actor_id="admin-1",
        )


@pytest.mark.asyncio
async def test_expired_invitation_is_cancelled_before_reinviting():
    expired = SimpleNamespace(
        id="old-invite",
        email="new@example.com",
        username="old-user",
        department_id="dept-1",
        role=SimpleNamespace(code="ROLE_EMPLOYEE"),
        department_scope_ids=[],
        expires_at=datetime.now() - timedelta(minutes=1),
        used_at=None,
        reason=None,
        cancelled_at=None,
        cancelled_by=None,
    )
    service = build_service(role_code="ROLE_EMPLOYEE", unresolved=expired)

    invitation, invite_code = await service.create_invitation(
        email="new@example.com",
        username="new-user",
        department_id="dept-1",
        role_code="ROLE_EMPLOYEE",
        department_scope_ids=[],
        expires_at=None,
        reason="普通员工入职",
        actor_id="admin-1",
    )

    assert expired.cancelled_at is not None
    assert expired.cancelled_by == "admin-1"
    assert invitation.email == "new@example.com"
    assert len(invite_code) >= 20
    assert service.session.flush_count >= 2


@pytest.mark.asyncio
async def test_register_consumes_invitation_and_grants_initial_role():
    role = SimpleNamespace(code="ROLE_HR_RECRUITER")
    invitation = SimpleNamespace(
        id="invite-1",
        email="new@example.com",
        username="new-user",
        department_id="dept-1",
        role=role,
        department_scope_ids=["dept-1"],
        expires_at=datetime.now() + timedelta(days=1),
        invited_by="admin-1",
        reason="负责研发招聘",
        used_at=None,
        used_by_user_id=None,
    )
    service = build_service(invitation=invitation)

    user = await service.register_from_invitation(
        email="new@example.com",
        invite_code="valid-code",
            user_data={"username": "new-user", "realname": "新用户", "password": "Secure!Pass2026"},
    )

    assert user is not None
    assert user.username == "new-user"
    assert invitation.used_at is not None
    assert invitation.used_by_user_id == "user-1"
    assert service.role_assignment_service.grant_kwargs["role_code"] == "ROLE_HR_RECRUITER"
    assert service.role_assignment_service.grant_kwargs["department_ids"] == ["dept-1"]
    assert service.session.added[-1].action == "invitation.consume"


@pytest.mark.asyncio
async def test_register_rejects_username_different_from_invitation():
    role = SimpleNamespace(code="ROLE_EMPLOYEE")
    invitation = SimpleNamespace(
        id="invite-1",
        email="new@example.com",
        username="assigned-user",
        department_id="dept-1",
        role=role,
        department_scope_ids=[],
        expires_at=datetime.now() + timedelta(days=1),
        invited_by="admin-1",
        reason=None,
        used_at=None,
        used_by_user_id=None,
    )
    service = build_service(role_code="ROLE_EMPLOYEE", invitation=invitation)

    with pytest.raises(InvitationValidationError, match="邀请指定"):
        await service.register_from_invitation(
            email="new@example.com",
            invite_code="valid-code",
            user_data={"username": "another-user", "realname": "新用户", "password": "Secure!Pass2026"},
        )
