"""候选人检索索引全量回灌服务。"""

from dataclasses import dataclass
from datetime import datetime

from loguru import logger

from models import AsyncSessionFactory
from repository.candidate_repo import CandidateRepo
from repository.candidate_search_repo import (
    CandidateIndexOutboxRepo,
    CandidateSearchProfileRepo,
)
from services.candidate_index_sync_service import CandidateIndexSyncService
from services.candidate_search_profile_service import CandidateSearchProfileService


@dataclass
class CandidateIndexBackfillResult:
    """一次全量回灌的汇总结果。"""

    scanned_candidates: int = 0
    rebuilt_profiles: int = 0
    unchanged_profiles: int = 0
    missing_candidates: int = 0
    profile_failures: int = 0
    indexed_events: int = 0
    sync_failures: int = 0


class CandidateIndexBackfillService:
    """按批重建候选人画像，并通过 Outbox 同步到 Milvus。"""

    def __init__(
        self,
        *,
        session_factory=AsyncSessionFactory,
        sync_service: CandidateIndexSyncService | None = None,
    ):
        self.session_factory = session_factory
        self.sync_service = sync_service or CandidateIndexSyncService()

    async def rebuild_all(
        self,
        *,
        batch_size: int = 100,
        force_reindex: bool = True,
        dry_run: bool = False,
    ) -> CandidateIndexBackfillResult:
        """执行全量回灌。

        默认强制重建索引，适合新建或清空 Milvus Collection 后执行。传入
        ``force_reindex=False`` 时，仅为缺失或内容变化的画像创建 Outbox 事件。
        ``dry_run`` 只统计影响范围，不会写入 PostgreSQL 或 Milvus。
        """

        if batch_size <= 0:
            raise ValueError("batch_size 必须大于 0")

        result = CandidateIndexBackfillResult()
        cursor_created_at: datetime | None = None
        cursor_id: str | None = None

        while True:
            candidates = await self._load_candidate_batch(
                batch_size=batch_size,
                cursor_created_at=cursor_created_at,
                cursor_id=cursor_id,
            )
            if not candidates:
                break

            result.scanned_candidates += len(candidates)
            for candidate in candidates:
                await self._rebuild_one_candidate(
                    candidate_id=candidate.id,
                    force_reindex=force_reindex,
                    dry_run=dry_run,
                    result=result,
                )

            # 游标必须使用本批最后一条已读取记录，避免新插入的数据扰乱分页。
            last_candidate = candidates[-1]
            cursor_created_at = last_candidate.created_at
            cursor_id = last_candidate.id

            if not dry_run:
                try:
                    result.indexed_events += await self.sync_service.sync_pending_events(
                        limit=batch_size
                    )
                except Exception as exc:
                    # 单批同步失败不丢失 Outbox 事件，后续批次或定时任务可重试。
                    result.sync_failures += 1
                    logger.exception(f"候选人索引回灌同步失败：{exc}")

        return result

    async def _load_candidate_batch(
        self,
        *,
        batch_size: int,
        cursor_created_at: datetime | None,
        cursor_id: str | None,
    ):
        """读取一批候选人 ID 和游标信息。"""

        async with self.session_factory() as session:
            candidate_repo = CandidateRepo(session)
            return await candidate_repo.list_for_indexing(
                limit=batch_size,
                cursor_created_at=cursor_created_at,
                cursor_id=cursor_id,
            )

    async def _rebuild_one_candidate(
        self,
        *,
        candidate_id: str,
        force_reindex: bool,
        dry_run: bool,
        result: CandidateIndexBackfillResult,
    ) -> None:
        """在独立事务中处理一个候选人，防止单条脏数据阻塞整批回灌。"""

        try:
            async with self.session_factory() as session:
                async with session.begin():
                    candidate_repo = CandidateRepo(session)
                    candidate = await candidate_repo.get_by_id(candidate_id)
                    if not candidate:
                        result.missing_candidates += 1
                        return

                    profile_repo = CandidateSearchProfileRepo(session)
                    old_profile = await profile_repo.get_by_candidate_id(candidate.id)
                    profile_service = CandidateSearchProfileService(
                        profile_repo=profile_repo,
                        outbox_repo=CandidateIndexOutboxRepo(session),
                    )
                    profile_text = profile_service.build_profile_text(candidate)
                    should_rebuild = (
                        force_reindex
                        or old_profile is None
                        or old_profile.profile_text != profile_text
                    )

                    if not should_rebuild:
                        result.unchanged_profiles += 1
                        return

                    result.rebuilt_profiles += 1
                    if not dry_run:
                        await profile_service.rebuild_candidate_profile(
                            candidate,
                            force_reindex=force_reindex,
                        )
        except Exception as exc:
            result.profile_failures += 1
            logger.exception(
                f"候选人画像回灌失败，candidate_id={candidate_id}：{exc}"
            )
