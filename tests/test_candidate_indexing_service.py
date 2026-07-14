from types import SimpleNamespace

import pytest

from models.candidate import CandidateStatusEnum
from models.candidate_search import CandidateIndexEventTypeEnum
from services.candidate_indexing_service import CandidateIndexingService


class FakeCandidateRepo:
    async def get_by_id(self, candidate_id):
        return SimpleNamespace(
            id=candidate_id,
            position_id="position-1",
            creator_id="creator-1",
            status=CandidateStatusEnum.APPLICATION,
            position=SimpleNamespace(
                department_id="department-1",
                creator_id="position-creator-1",
            ),
        )


class FakeProfileRepo:
    def __init__(self):
        self.indexed = []

    async def get_by_candidate_id(self, candidate_id):
        return SimpleNamespace(
            candidate_id=candidate_id,
            profile_text="Python FastAPI LangChain Milvus",
            profile_version=1,
        )

    async def mark_indexed(self, **kwargs):
        self.indexed.append(kwargs)


class FakeOutboxRepo:
    def __init__(self, events):
        self.events = events
        self.processing = []
        self.succeeded = []
        self.failed = []

    async def list_pending_events(self, limit=20):
        return self.events[:limit]

    async def mark_processing(self, event_id):
        self.processing.append(event_id)

    async def mark_succeeded(self, event_id):
        self.succeeded.append(event_id)

    async def mark_failed(self, event_id, error):
        self.failed.append((event_id, error))


class FakeEmbeddingService:
    model = "fake-embedding"

    async def embed_query(self, text):
        return [0.1] * 1024


class FakeMilvusClient:
    def __init__(self):
        self.upserts = []

    def upsert(self, collection_name, data):
        self.upserts.append((collection_name, data))


@pytest.mark.asyncio
async def test_consume_pending_events_upserts_to_milvus():
    event = SimpleNamespace(
        id="event-1",
        candidate_id="candidate-1",
        event_type=CandidateIndexEventTypeEnum.UPSERT,
        profile_version=1,
    )
    profile_repo = FakeProfileRepo()
    outbox_repo = FakeOutboxRepo([event])
    milvus_client = FakeMilvusClient()

    service = CandidateIndexingService(
        candidate_repo=FakeCandidateRepo(),
        profile_repo=profile_repo,
        outbox_repo=outbox_repo,
        embedding_service=FakeEmbeddingService(),
        milvus_client=milvus_client,
    )

    count = await service.consume_pending_events()

    assert count == 1
    assert outbox_repo.processing == ["event-1"]
    assert outbox_repo.succeeded == ["event-1"]
    assert outbox_repo.failed == []
    assert len(milvus_client.upserts) == 1
    assert profile_repo.indexed[0]["candidate_id"] == "candidate-1"
    assert milvus_client.upserts[0][1][0]["creator_id"] == "position-creator-1"
