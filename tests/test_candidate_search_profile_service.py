from types import SimpleNamespace

import pytest

from models.candidate import CandidateStatusEnum
from services.candidate_search_profile_service import CandidateSearchProfileService


def test_build_profile_text_contains_searchable_fields():
    """画像文本应该包含技能、经历、岗位等可检索信息。"""

    service = CandidateSearchProfileService(
        profile_repo=None,
        outbox_repo=None,
    )

    candidate = SimpleNamespace(
        name="张三",
        status=CandidateStatusEnum.APPLICATION,
        position=SimpleNamespace(title="大模型应用工程师"),
        skills="Python, FastAPI, LangChain, Milvus",
        work_experience="3年后端开发经验，负责过招聘系统和RAG应用。",
        project_experience="做过基于Milvus的人才语义检索项目。",
        education_experience="本科，计算机科学与技术。",
        self_evaluation="学习能力强，熟悉大模型应用工程化。",
        other_information="可尽快到岗。",
        phone_number="13800138000",
        email="zhangsan@example.com",
        birthday="1995-01-01",
    )

    profile_text = service.build_profile_text(candidate)

    assert "张三" in profile_text
    assert "大模型应用工程师" in profile_text
    assert "Python" in profile_text
    assert "FastAPI" in profile_text
    assert "LangChain" in profile_text
    assert "Milvus" in profile_text
    assert "RAG" in profile_text


def test_build_profile_text_excludes_sensitive_fields():
    """画像文本不能包含手机号、邮箱、生日等敏感字段。"""

    service = CandidateSearchProfileService(
        profile_repo=None,
        outbox_repo=None,
    )

    candidate = SimpleNamespace(
        name="李四",
        status=CandidateStatusEnum.APPLICATION,
        position=SimpleNamespace(title="Python后端工程师"),
        skills="Python, PostgreSQL",
        work_experience="负责业务后端开发。",
        project_experience="做过内部管理系统。",
        education_experience="本科。",
        self_evaluation="沟通能力好。",
        other_information="无。",
        phone_number="13800138000",
        email="lisi@example.com",
        birthday="1996-06-01",
    )

    profile_text = service.build_profile_text(candidate)

    assert "13800138000" not in profile_text
    assert "lisi@example.com" not in profile_text
    assert "1996-06-01" not in profile_text


class FakeProfileRepo:
    def __init__(self, profile):
        self.profile = profile
        self.upsert_calls = []

    async def get_by_candidate_id(self, candidate_id):
        return self.profile

    async def upsert_profile(self, **kwargs):
        self.upsert_calls.append(kwargs)
        return SimpleNamespace(**kwargs)


class FakeOutboxRepo:
    def __init__(self):
        self.events = []

    async def create_event(self, **kwargs):
        self.events.append(kwargs)


@pytest.mark.asyncio
async def test_rebuild_candidate_profile_skips_unchanged_profile():
    """画像内容未变化时不应递增版本或创建新的 Outbox 事件。"""

    candidate = SimpleNamespace(
        id="candidate-1",
        name="王五",
        status=CandidateStatusEnum.APPLICATION,
        position=SimpleNamespace(title="Python 后端工程师"),
        skills="Python, FastAPI",
        work_experience="负责后端服务开发。",
        project_experience="做过人才检索系统。",
        education_experience="本科。",
        self_evaluation="学习能力强。",
        other_information="无。",
    )
    profile_text = CandidateSearchProfileService(
        profile_repo=None,
        outbox_repo=None,
    ).build_profile_text(candidate)
    old_profile = SimpleNamespace(
        candidate_id="candidate-1",
        profile_text=profile_text,
        profile_version=3,
    )
    profile_repo = FakeProfileRepo(old_profile)
    outbox_repo = FakeOutboxRepo()
    service = CandidateSearchProfileService(profile_repo, outbox_repo)

    result = await service.rebuild_candidate_profile(candidate)

    assert result is old_profile
    assert profile_repo.upsert_calls == []
    assert outbox_repo.events == []


@pytest.mark.asyncio
async def test_rebuild_candidate_profile_force_reindex_creates_new_version():
    """全量回灌强制重建时，即使文本不变也应创建新的索引事件。"""

    candidate = SimpleNamespace(
        id="candidate-1",
        name="王五",
        status=CandidateStatusEnum.APPLICATION,
        position=SimpleNamespace(title="Python 后端工程师"),
        skills="Python, FastAPI",
        work_experience="负责后端服务开发。",
        project_experience="做过人才检索系统。",
        education_experience="本科。",
        self_evaluation="学习能力强。",
        other_information="无。",
    )
    profile_text = CandidateSearchProfileService(
        profile_repo=None,
        outbox_repo=None,
    ).build_profile_text(candidate)
    old_profile = SimpleNamespace(
        candidate_id="candidate-1",
        profile_text=profile_text,
        profile_version=3,
    )
    profile_repo = FakeProfileRepo(old_profile)
    outbox_repo = FakeOutboxRepo()
    service = CandidateSearchProfileService(profile_repo, outbox_repo)

    await service.rebuild_candidate_profile(candidate, force_reindex=True)

    assert profile_repo.upsert_calls[0]["profile_version"] == 4
    assert outbox_repo.events[0]["profile_version"] == 4
