from models.candidate import CandidateStatusEnum
from models.user import UserModel
from rag.embeddings import EmbeddingService
from rag.milvus_client import get_milvus_client
from repository.candidate_repo import CandidateRepo
from settings import settings


class TalentSearchService:
    """人才库语义检索服务。

    第一阶段只做检索服务，不接 Agent。
    """

    def __init__(
        self,
        candidate_repo: CandidateRepo,
        embedding_service: EmbeddingService | None = None,
        milvus_client=None,
    ):
        self.candidate_repo = candidate_repo
        self.embedding_service = embedding_service or EmbeddingService()
        self.milvus_client = milvus_client or get_milvus_client()

    async def search(
        self,
        *,
        query: str,
        current_user: UserModel,
        top_k: int = 10,
        position_id: str | None = None,
        status: CandidateStatusEnum | None = None,
    ) -> list[dict]:
        """根据自然语言检索候选人。"""

        vector = await self.embedding_service.embed_query(query)

        if len(vector) != settings.MILVUS_CANDIDATE_VECTOR_DIM:
            raise ValueError(
                f"Embedding维度不匹配：期望 {settings.MILVUS_CANDIDATE_VECTOR_DIM}，实际 {len(vector)}"
            )

        milvus_filter = self._build_milvus_filter(
            current_user=current_user,
            position_id=position_id,
            status=status,
        )

        search_result = self.milvus_client.search(
            collection_name=settings.MILVUS_CANDIDATE_COLLECTION,
            data=[vector],
            anns_field="dense_vector",
            limit=top_k,
            filter=milvus_filter,
            output_fields=[
                "candidate_id",
                "profile_text",
                "position_id",
                "department_id",
                "creator_id",
                "status",
                "profile_version",
            ],
        )

        hits = search_result[0] if search_result else []
        candidate_ids = [hit["entity"]["candidate_id"] for hit in hits]
        score_map = {
            hit["entity"]["candidate_id"]: float(hit.get("distance", 0.0))
            for hit in hits
        }
        profile_text_map = {
            hit["entity"]["candidate_id"]: hit["entity"].get("profile_text")
            for hit in hits
        }

        # PostgreSQL 二次复核权限和最新候选人状态。
        candidates = await self.candidate_repo.list_visible_by_ids(
            candidate_ids=candidate_ids,
            current_user=current_user,
        )

        return [
            {
                "candidate_id": candidate.id,
                "name": candidate.name,
                "position_title": candidate.position.title if candidate.position else None,
                "status": candidate.status,
                "score": score_map.get(candidate.id, 0.0),
                "profile_text": profile_text_map.get(candidate.id),
            }
            for candidate in candidates
        ]

    def _build_milvus_filter(
        self,
        *,
        current_user: UserModel,
        position_id: str | None,
        status: CandidateStatusEnum | None,
    ) -> str:
        """构造 Milvus 标量过滤表达式。"""

        filters = []

        if not current_user.is_superuser:
            if current_user.is_hr:
                managed_department_ids = [
                    d.id for d in getattr(current_user, "managed_departments", []) or []
                ]
                if managed_department_ids:
                    quoted_ids = ", ".join(f'"{department_id}"' for department_id in managed_department_ids)
                    filters.append(f"department_id in [{quoted_ids}]")
            else:
                filters.append(f'creator_id == "{current_user.id}"')

        if position_id:
            filters.append(f'position_id == "{position_id}"')

        if status:
            filters.append(f'status == "{status.value}"')

        return " and ".join(filters)