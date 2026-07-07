from datetime import datetime
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert

from models.candidate_search import (
    CandidateIndexEventStatusEnum,
    CandidateIndexEventTypeEnum,
    CandidateIndexOutboxModel,
    CandidateSearchProfileModel,
)
from . import BaseRepo

class CandidateSearchProfileRepo(BaseRepo):
    async def get_by_candidate_id(self, candidate_id: str) -> CandidateSearchProfileModel | None:
        return await self.session.scalar(
            select(CandidateSearchProfileModel).where(
                CandidateSearchProfileModel.candidate_id == candidate_id
            )
        )

    async def upsert_profile(
        self,
        *,
        candidate_id: str,
        profile_text: str,
        profile_version: int,
        embedding_model: str | None = None,
    ) -> CandidateSearchProfileModel:
        """写入或更新候选人检索画像。"""

        stmt = (
            insert(CandidateSearchProfileModel)
            .values(
                candidate_id=candidate_id,
                profile_text=profile_text,
                profile_version=profile_version,
                embedding_model=embedding_model,
            )
            .on_conflict_do_update(
                index_elements=[CandidateSearchProfileModel.candidate_id],
                set_={
                    "profile_text": profile_text,
                    "profile_version": profile_version,
                    "embedding_model": embedding_model,
                    "indexed_version": None,
                    "last_index_error": None,
                    "updated_at": datetime.now(),
                },
            )
            .returning(CandidateSearchProfileModel)
        )

        return await self.session.scalar(stmt)

    async def mark_indexed(
        self,
        *,
        candidate_id: str,
        profile_version: int,
        embedding_model: str,
    ) -> None:
        stmt = (
            update(CandidateSearchProfileModel)
            .where(CandidateSearchProfileModel.candidate_id == candidate_id)
            .values(
                indexed_version=profile_version,
                embedding_model=embedding_model,
                last_index_error=None,
                updated_at=datetime.now(),
            )
        )
        await self.session.execute(stmt)

class CandidateIndexOutboxRepo(BaseRepo):
    async def create_event(
        self,
        *,
        candidate_id: str,
        event_type: CandidateIndexEventTypeEnum,
        profile_version: int,
    ) -> CandidateIndexOutboxModel | None:
        """创建索引同步事件。

        如果同一个候选人、同一种事件、同一个版本已经存在，则不重复创建。
        """

        stmt = (
            insert(CandidateIndexOutboxModel)
            .values(
                candidate_id=candidate_id,
                event_type=event_type,
                profile_version=profile_version,
                status=CandidateIndexEventStatusEnum.PENDING,
                retry_count=0,
            )
            .on_conflict_do_nothing(
                constraint="uq_candidate_index_outbox_candidate_event_version"
            )
            .returning(CandidateIndexOutboxModel)
        )

        event = await self.session.scalar(stmt)
        return event