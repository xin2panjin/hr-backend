from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from services import candidate_index_backfill_service as backfill_module
from services.candidate_index_backfill_service import CandidateIndexBackfillService


class FakeSession:
    """模拟 SQLAlchemy 的会话和事务上下文。"""

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False

    def begin(self):
        return self


class FakeCandidateRepo:
    candidates = []

    def __init__(self, session):
        self.session = session

    async def list_for_indexing(self, *, limit, cursor_created_at, cursor_id):
        candidates = self.candidates
        if cursor_created_at is not None:
            candidates = [
                candidate
                for candidate in candidates
                if (candidate.created_at, candidate.id)
                > (cursor_created_at, cursor_id)
            ]
        return candidates[:limit]

    async def get_by_id(self, candidate_id):
        return next(
            (candidate for candidate in self.candidates if candidate.id == candidate_id),
            None,
        )


class FakeProfileRepo:
    profiles = {}

    def __init__(self, session):
        self.session = session

    async def get_by_candidate_id(self, candidate_id):
        return self.profiles.get(candidate_id)


class FakeOutboxRepo:
    def __init__(self, session):
        self.session = session


class FakeProfileService:
    rebuild_calls = []

    def __init__(self, profile_repo, outbox_repo):
        self.profile_repo = profile_repo
        self.outbox_repo = outbox_repo

    def build_profile_text(self, candidate):
        return candidate.profile_text

    async def rebuild_candidate_profile(self, candidate, *, force_reindex):
        self.rebuild_calls.append((candidate.id, force_reindex))


class FakeSyncService:
    def __init__(self, counts):
        self.counts = list(counts)
        self.calls = []

    async def sync_pending_events(self, limit):
        self.calls.append(limit)
        return self.counts.pop(0)


def build_candidate(candidate_id, created_at, profile_text):
    return SimpleNamespace(
        id=candidate_id,
        created_at=created_at,
        profile_text=profile_text,
    )


@pytest.fixture(autouse=True)
def replace_backfill_dependencies(monkeypatch):
    FakeCandidateRepo.candidates = []
    FakeProfileRepo.profiles = {}
    FakeProfileService.rebuild_calls = []
    monkeypatch.setattr(backfill_module, "CandidateRepo", FakeCandidateRepo)
    monkeypatch.setattr(
        backfill_module,
        "CandidateSearchProfileRepo",
        FakeProfileRepo,
    )
    monkeypatch.setattr(backfill_module, "CandidateIndexOutboxRepo", FakeOutboxRepo)
    monkeypatch.setattr(
        backfill_module,
        "CandidateSearchProfileService",
        FakeProfileService,
    )


@pytest.mark.asyncio
async def test_rebuild_all_pages_candidates_and_only_updates_changed_profiles():
    now = datetime(2026, 7, 13, 10, 0, 0)
    FakeCandidateRepo.candidates = [
        build_candidate("candidate-1", now, "画像一"),
        build_candidate("candidate-2", now + timedelta(seconds=1), "画像二"),
        build_candidate("candidate-3", now + timedelta(seconds=2), "画像三"),
    ]
    FakeProfileRepo.profiles = {
        "candidate-1": SimpleNamespace(profile_text="画像一"),
        "candidate-2": SimpleNamespace(profile_text="旧画像二"),
    }
    sync_service = FakeSyncService([2, 1])
    service = CandidateIndexBackfillService(
        session_factory=FakeSession,
        sync_service=sync_service,
    )

    result = await service.rebuild_all(
        batch_size=2,
        force_reindex=False,
    )

    assert result.scanned_candidates == 3
    assert result.rebuilt_profiles == 2
    assert result.unchanged_profiles == 1
    assert result.profile_failures == 0
    assert result.indexed_events == 3
    assert FakeProfileService.rebuild_calls == [
        ("candidate-2", False),
        ("candidate-3", False),
    ]
    assert sync_service.calls == [2, 2]


@pytest.mark.asyncio
async def test_rebuild_all_dry_run_does_not_write_or_sync():
    FakeCandidateRepo.candidates = [
        build_candidate("candidate-1", datetime(2026, 7, 13, 10, 0, 0), "画像一"),
    ]
    sync_service = FakeSyncService([])
    service = CandidateIndexBackfillService(
        session_factory=FakeSession,
        sync_service=sync_service,
    )

    result = await service.rebuild_all(
        batch_size=10,
        force_reindex=True,
        dry_run=True,
    )

    assert result.scanned_candidates == 1
    assert result.rebuilt_profiles == 1
    assert FakeProfileService.rebuild_calls == []
    assert sync_service.calls == []
