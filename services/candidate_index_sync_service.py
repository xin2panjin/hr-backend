"""候选人索引 Outbox 的应用服务入口。"""

from models import AsyncSessionFactory
from repository.candidate_repo import CandidateRepo
from repository.candidate_search_repo import (
    CandidateIndexOutboxRepo,
    CandidateSearchProfileRepo,
)
from services.candidate_indexing_service import CandidateIndexingService


class CandidateIndexSyncService:
    """统一消费候选人索引 Outbox。"""

    async def sync_pending_events(self, limit: int = 20) -> int:
        """同步一批待处理索引事件到 Milvus。"""

        async with AsyncSessionFactory() as session:
            async with session.begin():
                service = CandidateIndexingService(
                    candidate_repo=CandidateRepo(session),
                    profile_repo=CandidateSearchProfileRepo(session),
                    outbox_repo=CandidateIndexOutboxRepo(session),
                )
                return await service.consume_pending_events(limit=limit)
