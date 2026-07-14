from datetime import datetime

from models.candidate_search import (
    CandidateIndexEventTypeEnum,
    CandidateIndexOutboxModel,
)
from rag.embeddings import EmbeddingService
from rag.milvus_client import get_milvus_client
from repository.candidate_repo import CandidateRepo
from repository.candidate_search_repo import (
    CandidateIndexOutboxRepo,
    CandidateSearchProfileRepo,
)
from settings import settings


class CandidateIndexingService:
    """候选人 Milvus 索引服务。

    负责消费 outbox 事件，把 PostgreSQL 中的候选人画像同步到 Milvus。
    """

    def __init__(
        self,
        candidate_repo: CandidateRepo,
        profile_repo: CandidateSearchProfileRepo,
        outbox_repo: CandidateIndexOutboxRepo,
        embedding_service: EmbeddingService | None = None,
        milvus_client=None,
    ):
        self.candidate_repo = candidate_repo
        self.profile_repo = profile_repo
        self.outbox_repo = outbox_repo
        self.embedding_service = embedding_service or EmbeddingService()
        self.milvus_client = milvus_client or get_milvus_client()

    async def consume_pending_events(self, limit: int = 20) -> int:
        """消费一批待处理索引事件，返回成功处理数量。"""

        events = await self.outbox_repo.list_pending_events(limit=limit)
        success_count = 0

        for event in events:
            try:
                await self.outbox_repo.mark_processing(event.id)
                await self.process_event(event)
                await self.outbox_repo.mark_succeeded(event.id)
                success_count += 1
            except Exception as exc:
                await self.outbox_repo.mark_failed(event.id, str(exc))

        return success_count

    async def process_event(self, event: CandidateIndexOutboxModel) -> None:
        """处理单个索引事件。"""

        if event.event_type == CandidateIndexEventTypeEnum.DELETE:
            self.milvus_client.delete(
                collection_name=settings.MILVUS_CANDIDATE_COLLECTION,
                ids=[event.candidate_id],
            )
            return

        profile = await self.profile_repo.get_by_candidate_id(event.candidate_id)
        if not profile:
            raise ValueError(f"候选人检索画像不存在：{event.candidate_id}")

        # 如果 outbox 事件版本落后于最新画像版本，说明已经过期，直接跳过。
        if event.profile_version < profile.profile_version:
            return

        candidate = await self.candidate_repo.get_by_id(event.candidate_id)
        if not candidate:
            raise ValueError(f"候选人不存在：{event.candidate_id}")

        vector = await self.embedding_service.embed_query(profile.profile_text)

        if len(vector) != settings.MILVUS_CANDIDATE_VECTOR_DIM:
            raise ValueError(
                f"Embedding维度不匹配：期望 {settings.MILVUS_CANDIDATE_VECTOR_DIM}，实际 {len(vector)}"
            )

        position = candidate.position
        department_id = position.department_id if position else ""
        # 检索权限对普通用户按“职位创建人”判断，Milvus 元数据必须与
        # PostgreSQL CandidatePolicy 使用同一归属字段。
        position_creator_id = getattr(position, "creator_id", "") if position else ""

        self.milvus_client.upsert(
            collection_name=settings.MILVUS_CANDIDATE_COLLECTION,
            data=[
                {
                    "candidate_id": candidate.id,
                    "profile_text": profile.profile_text,
                    "dense_vector": vector,
                    "department_id": department_id or "",
                    "position_id": candidate.position_id or "",
                    "creator_id": position_creator_id or "",
                    "status": candidate.status.value if candidate.status else "",
                    "profile_version": profile.profile_version,
                    "embedding_model": self.embedding_service.model,
                    "updated_at": int(datetime.now().timestamp()),
                }
            ],
        )

        await self.profile_repo.mark_indexed(
            candidate_id=candidate.id,
            profile_version=profile.profile_version,
            embedding_model=self.embedding_service.model,
        )
