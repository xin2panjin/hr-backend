from types import SimpleNamespace

import pytest

from models.candidate import CandidateStatusEnum
from services.talent_search_service import TalentSearchService


class FakeEmbeddingService:
    async def embed_query(self, text):
        return [0.1] * 1024


class FakeMilvusClient:
    def __init__(self):
        self.search_calls = []

    def search(self, **kwargs):
        self.search_calls.append(kwargs)
        return [
            [
                {
                    "distance": 0.91,
                    "entity": {
                        "candidate_id": "candidate-1",
                        "profile_text": "Python FastAPI 大模型应用",
                    },
                }
            ]
        ]


class FakeCandidateRepo:
    async def list_visible_by_ids(self, *, candidate_ids, current_user):
        assert candidate_ids == ["candidate-1"]
        return [
            SimpleNamespace(
                id="candidate-1",
                name="张三",
                status=CandidateStatusEnum.APPLICATION,
                position=SimpleNamespace(title="后端工程师"),
            )
        ]


@pytest.mark.asyncio
async def test_talent_search_returns_candidates():
    milvus_client = FakeMilvusClient()
    service = TalentSearchService(
        candidate_repo=FakeCandidateRepo(),
        embedding_service=FakeEmbeddingService(),
        milvus_client=milvus_client,
    )
    current_user = SimpleNamespace(
        id="user-1",
        is_superuser=True,
        is_hr=False,
    )

    result = await service.search(
        query="找一个会 FastAPI 和大模型应用的人",
        current_user=current_user,
    )

    assert result[0]["candidate_id"] == "candidate-1"
    assert result[0]["name"] == "张三"
    assert result[0]["score"] == 0.91
    assert milvus_client.search_calls[0]["collection_name"] == "candidate_profiles_v1"


@pytest.mark.asyncio
async def test_talent_search_builds_creator_filter_for_normal_user():
    service = TalentSearchService(
        candidate_repo=FakeCandidateRepo(),
        embedding_service=FakeEmbeddingService(),
        milvus_client=FakeMilvusClient(),
    )
    current_user = SimpleNamespace(
        id="user-1",
        is_superuser=False,
        is_hr=False,
    )

    milvus_filter = service._build_milvus_filter(
        current_user=current_user,
        position_id=None,
        status=None,
    )

    assert milvus_filter == 'creator_id == "user-1"'