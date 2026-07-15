"""人才检索离线评测脚本的权限上下文测试。"""

from types import SimpleNamespace

import pytest

from scripts import evaluate_talent_search as evaluation_module


@pytest.mark.asyncio
async def test_get_evaluation_user_loads_active_iam_roles(monkeypatch):
    """评测脚本必须携带有效角色，不能被候选人策略误判为无权限。"""

    user = SimpleNamespace(id="boss-id", iam_roles=[])
    active_roles = [SimpleNamespace(role=SimpleNamespace(code="ROLE_SYSTEM_ADMIN"))]

    class FakeUserRepo:
        def __init__(self, session):
            self.session = session

        async def get_by_id(self, user_id):
            assert user_id == "boss-id"
            return user

    class FakeIamRepo:
        def __init__(self, session):
            self.session = session

        async def get_active_user_roles(self, user_id):
            assert user_id == "boss-id"
            return active_roles

    monkeypatch.setattr(evaluation_module, "UserRepo", FakeUserRepo)
    monkeypatch.setattr(evaluation_module, "IamRepo", FakeIamRepo)

    result = await evaluation_module.get_evaluation_user(
        session=object(),
        user_id="boss-id",
    )

    assert result is user
    assert result.iam_roles == active_roles


@pytest.mark.asyncio
async def test_get_evaluation_user_rejects_missing_user(monkeypatch):
    """不存在的评测用户应在执行检索前失败。"""

    class FakeUserRepo:
        def __init__(self, session):
            self.session = session

        async def get_by_id(self, user_id):
            return None

    monkeypatch.setattr(evaluation_module, "UserRepo", FakeUserRepo)

    with pytest.raises(ValueError, match="评测用户不存在"):
        await evaluation_module.get_evaluation_user(
            session=object(),
            user_id="missing-user",
        )
