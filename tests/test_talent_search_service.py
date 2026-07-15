from types import SimpleNamespace

import pytest

from models.candidate import CandidateStatusEnum
from rag.retrieval_types import (
    RetrievalHit,
    RetrievalMode,
    RetrievalSource,
    SearchHit,
)
from services import talent_search_service as talent_search_module
from services.talent_search_service import TalentSearchService
from iam.permissions import RoleCode
from settings import settings


def build_actor(user_id: str, *role_codes: str):
    return SimpleNamespace(
        id=user_id,
        iam_roles=[SimpleNamespace(role=SimpleNamespace(code=role_code), scopes=[]) for role_code in role_codes],
    )


class FakeRetriever:
    def __init__(self):
        self.calls = []

    async def retrieve(self, request, *, mode):
        self.calls.append((request, mode))
        return [
            RetrievalHit(
                candidate_id="candidate-1",
                score=0.91,
                profile_text="Python FastAPI 大模型应用",
                rank_source=RetrievalSource.HYBRID,
            ),
            RetrievalHit(
                candidate_id="candidate-2",
                score=0.80,
                profile_text="Python 风控平台",
                rank_source=RetrievalSource.HYBRID,
            ),
        ]


class FakeCandidateRepo:
    async def list_visible_by_ids(self, *, candidate_ids, current_user):
        assert candidate_ids == ["candidate-1", "candidate-2"]
        return [
            SimpleNamespace(
                id="candidate-1",
                name="张三",
                status=CandidateStatusEnum.APPLICATION,
                position=SimpleNamespace(title="后端工程师"),
            ),
            SimpleNamespace(
                id="candidate-2",
                name="李四",
                status=CandidateStatusEnum.APPLICATION,
                position=SimpleNamespace(title="Python 工程师"),
            ),
        ]


class GenericFakeRetriever:
    """模拟通用 Retriever 返回的 SearchHit。"""

    async def retrieve(self, request, *, mode):
        return [
            SearchHit(
                entity_id="candidate-1",
                score=0.91,
                text="Python FastAPI 大模型应用",
                rank_source=RetrievalSource.HYBRID,
            ),
            SearchHit(
                entity_id="candidate-2",
                score=0.80,
                text="Python 风控平台",
                rank_source=RetrievalSource.HYBRID,
            ),
        ]


class CapturingGenericReranker:
    """验证人才 Service 在候选人适配前调用通用 Reranker。"""

    def __init__(self):
        self.received_hits = []

    async def rerank(self, *, query, hits, trace_id=None):
        self.received_hits = list(hits)
        return list(hits)


def test_talent_search_binds_candidate_collection_schema(monkeypatch):
    """候选人 Service 必须显式绑定自身 Collection，不能依赖通用默认值。"""

    captured = {}

    class CapturingRetriever:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(
        talent_search_module,
        "MilvusHybridRetriever",
        CapturingRetriever,
    )

    TalentSearchService(candidate_repo=FakeCandidateRepo())

    schema = captured["collection_schema"]
    assert schema.collection_name == talent_search_module.settings.MILVUS_CANDIDATE_COLLECTION
    assert schema.primary_key_field == "candidate_id"
    assert schema.text_field == "profile_text"
    assert schema.vector_dim == talent_search_module.settings.MILVUS_CANDIDATE_VECTOR_DIM


@pytest.mark.asyncio
async def test_talent_search_returns_candidates(monkeypatch):
    from settings import settings

    # 该测试验证 hybrid 契约，不能依赖开发机 .env 的实际检索模式。
    monkeypatch.setattr(settings, "TALENT_SEARCH_RETRIEVAL_MODE", "hybrid")
    retriever = FakeRetriever()
    service = TalentSearchService(
        candidate_repo=FakeCandidateRepo(),
        retriever=retriever,
    )
    current_user = build_actor("user-1", RoleCode.SYSTEM_ADMIN.value)

    result = await service.search(
        query="找一个会 FastAPI 和大模型应用的人",
        current_user=current_user,
    )

    assert result[0]["candidate_id"] == "candidate-1"
    assert result[0]["name"] == "张三"
    assert result[0]["score"] == 0.91
    assert len(result) == 2
    assert retriever.calls[0][1] == RetrievalMode.HYBRID


@pytest.mark.asyncio
async def test_talent_search_adapts_generic_retriever_hits(monkeypatch):
    """人才 Service 应将通用命中适配回候选人权限与卡片链路。"""

    monkeypatch.setattr(settings, "TALENT_SEARCH_RERANK_ENABLED", False)
    service = TalentSearchService(
        candidate_repo=FakeCandidateRepo(),
        retriever=GenericFakeRetriever(),
    )
    current_user = build_actor("user-1", RoleCode.SYSTEM_ADMIN.value)

    result = await service.search(query="Python", current_user=current_user)

    assert [item["candidate_id"] for item in result] == ["candidate-1", "candidate-2"]
    assert result[0]["profile_text"] == "Python FastAPI 大模型应用"


@pytest.mark.asyncio
async def test_talent_search_passes_generic_hits_to_reranker(monkeypatch):
    """Reranker 应接收 SearchHit，候选人适配只发生在业务边界。"""

    monkeypatch.setattr(settings, "TALENT_SEARCH_RERANK_ENABLED", True)
    reranker = CapturingGenericReranker()
    service = TalentSearchService(
        candidate_repo=FakeCandidateRepo(),
        retriever=GenericFakeRetriever(),
        reranker=reranker,
    )
    current_user = build_actor("user-1", RoleCode.SYSTEM_ADMIN.value)

    trace = await service.search_with_trace(query="Python", current_user=current_user)

    assert all(isinstance(hit, SearchHit) for hit in reranker.received_hits)
    assert [hit.candidate_id for hit in trace.retrieved_hits] == [
        "candidate-1",
        "candidate-2",
    ]
    assert [hit.candidate_id for hit in trace.reranked_hits] == [
        "candidate-1",
        "candidate-2",
    ]

@pytest.mark.asyncio
async def test_talent_search_builds_creator_filter_for_normal_user():
    service = TalentSearchService(
        candidate_repo=FakeCandidateRepo(),
        retriever=FakeRetriever(),
    )
    current_user = build_actor("user-1", RoleCode.HIRING_MANAGER.value)

    milvus_filter = service._build_milvus_filter(
        current_user=current_user,
        position_id=None,
        status=None,
    )

    assert milvus_filter == 'creator_id == "user-1"'


@pytest.mark.asyncio
async def test_talent_search_denies_hr_without_managed_departments():
    service = TalentSearchService(
        candidate_repo=FakeCandidateRepo(),
        retriever=FakeRetriever(),
    )
    current_user = build_actor("hr-1", RoleCode.RECRUITER.value)

    milvus_filter = service._build_milvus_filter(
        current_user=current_user,
        position_id=None,
        status=None,
    )

    assert milvus_filter == 'candidate_id == "__no_candidate_access__"'


@pytest.mark.asyncio
async def test_talent_search_passes_configured_recall_parameters_and_keeps_top_k(monkeypatch):
    from settings import settings

    # 该测试验证 hybrid 契约，不能依赖开发机 .env 的实际检索模式。
    monkeypatch.setattr(settings, "TALENT_SEARCH_RETRIEVAL_MODE", "hybrid")
    retriever = FakeRetriever()
    service = TalentSearchService(
        candidate_repo=FakeCandidateRepo(),
        retriever=retriever,
    )
    current_user = build_actor("user-1", RoleCode.SYSTEM_ADMIN.value)

    result = await service.search(
        query="Python",
        current_user=current_user,
        top_k=1,
    )

    request, mode = retriever.calls[0]
    assert mode == RetrievalMode.HYBRID
    assert request.dense_recall_k == 30
    assert request.sparse_recall_k == 30
    assert request.hybrid_limit == 30
    assert len(result) == 1


@pytest.mark.asyncio
async def test_talent_search_uses_sparse_mode_from_settings(monkeypatch):
    from settings import settings

    monkeypatch.setattr(settings, "TALENT_SEARCH_RETRIEVAL_MODE", "sparse")
    retriever = FakeRetriever()
    service = TalentSearchService(
        candidate_repo=FakeCandidateRepo(),
        retriever=retriever,
    )
    current_user = build_actor("user-1", RoleCode.SYSTEM_ADMIN.value)

    await service.search(query="Python", current_user=current_user)

    assert retriever.calls[0][1] == RetrievalMode.SPARSE


@pytest.mark.asyncio
async def test_talent_search_allows_internal_evaluation_mode_override():
    retriever = FakeRetriever()
    service = TalentSearchService(
        candidate_repo=FakeCandidateRepo(),
        retriever=retriever,
    )
    current_user = build_actor("user-1", RoleCode.SYSTEM_ADMIN.value)

    await service.search(
        query="Python",
        current_user=current_user,
        retrieval_mode=RetrievalMode.DENSE,
    )

    assert retriever.calls[0][1] == RetrievalMode.DENSE
