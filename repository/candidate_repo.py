from datetime import datetime

from models.positions import PositionModel
from . import BaseRepo
from models.candidate import ResumeModel, CandidateModel
from sqlalchemy import select, update
from models.candidate import CandidateAIScoreModel
from sqlalchemy.orm import selectinload
from models.candidate import CandidateStatusEnum
from models.user import UserModel
from sqlalchemy import func, and_, or_
from iam.policies.candidate_policy import CandidatePolicy


class ResumeRepo(BaseRepo):
    async def create_resume(self, file_path: str, uploader_id: str) -> ResumeModel:
        resume = ResumeModel(file_path=file_path, uploader_id=uploader_id)
        self.session.add(resume)
        return resume

    async def get_by_id(self, resume_id: str) -> ResumeModel:
        return await self.session.scalar(select(ResumeModel).where(ResumeModel.id == resume_id))


class CandidateRepo(BaseRepo):
    async def create_candidate(self, candidate_info: dict) -> CandidateModel:
        candidate = CandidateModel(**candidate_info)
        self.session.add(candidate)
        await self.session.flush([candidate])
        await self.session.refresh(candidate, ['position', 'resume'])
        return candidate

    async def update_candidate_status(self, candidate_id: str, status: CandidateStatusEnum):
        stmt = update(CandidateModel).where(CandidateModel.id==candidate_id).values(status=status)
        await self.session.execute(stmt)

    async def get_by_id(self, candidate_id: str) -> CandidateModel | None:
        return await self.session.scalar(
            select(CandidateModel)
            .where(CandidateModel.id==candidate_id)
            .options(
                selectinload(CandidateModel.position).selectinload(PositionModel.creator),
                selectinload(CandidateModel.position).selectinload(PositionModel.department),
                selectinload(CandidateModel.resume).selectinload(ResumeModel.uploader),
                selectinload(CandidateModel.creator),
                selectinload(CandidateModel.ai_score),
            )
        )

    async def get_latest_by_email(self, email: str) -> CandidateModel | None:
        """按候选人邮箱查询最近一次投递记录，并预加载 Agent 流程需要的上下文。"""
        return await self.session.scalar(
            select(CandidateModel)
            .where(func.lower(CandidateModel.email) == email.strip().lower())
            .options(
                selectinload(CandidateModel.position).selectinload(PositionModel.creator),
                selectinload(CandidateModel.position).selectinload(PositionModel.department),
                selectinload(CandidateModel.resume).selectinload(ResumeModel.uploader),
                selectinload(CandidateModel.creator),
                selectinload(CandidateModel.ai_score),
            )
            .order_by(CandidateModel.created_at.desc())
            .limit(1)
        )

    async def list_for_indexing(
        self,
        *,
        limit: int,
        cursor_created_at: datetime | None = None,
        cursor_id: str | None = None,
    ) -> list[CandidateModel]:
        """按稳定游标分页读取候选人，用于检索索引全量回灌。

        该查询不做调用人的权限过滤，因为回灌属于系统级维护任务；候选人
        权限仍会在检索阶段通过 Milvus 条件和 PostgreSQL 二次复核执行。
        """

        if limit <= 0:
            raise ValueError("limit 必须大于 0")

        stmt = (
            select(CandidateModel)
            .options(selectinload(CandidateModel.position))
            .order_by(CandidateModel.created_at.asc(), CandidateModel.id.asc())
            .limit(limit)
        )

        if cursor_created_at is not None and cursor_id is not None:
            stmt = stmt.where(
                or_(
                    CandidateModel.created_at > cursor_created_at,
                    and_(
                        CandidateModel.created_at == cursor_created_at,
                        CandidateModel.id > cursor_id,
                    ),
                )
            )

        return list(await self.session.scalars(stmt))

    async def get_list(
        self,
        current_user: UserModel,
        position_id: str|None = None,
        status: CandidateStatusEnum|None = None,
        keyword: str | None = None,
        creator_id: str | None = None,
        created_at_start: datetime | None = None,
        created_at_end: datetime | None = None,
        page: int = 1,
        size: int = 10
    ) -> tuple[list[CandidateModel], int]:
        filters = []

        if position_id is not None:
            filters.append(CandidateModel.position_id == position_id)

        if status is not None:
            filters.append(CandidateModel.status == status)

        if creator_id is not None:
            filters.append(CandidateModel.creator_id == creator_id)

        if created_at_start is not None:
            filters.append(CandidateModel.created_at >= created_at_start)

        if created_at_end is not None:
            filters.append(CandidateModel.created_at <= created_at_end)

        if keyword and keyword.strip():
            pattern = f"%{keyword.strip()}%"
            filters.append(
                or_(
                    CandidateModel.name.ilike(pattern),
                    CandidateModel.email.ilike(pattern),
                    CandidateModel.phone_number.ilike(pattern),
                )
            )

        scope = CandidatePolicy.resolve_scope(current_user)
        stmt = CandidatePolicy.apply_sql_scope(select(CandidateModel), scope).where(*filters)
        count_stmt = CandidatePolicy.apply_sql_scope(
            select(func.count(CandidateModel.id)),
            scope,
        ).where(*filters)

        total = int(await self.session.scalar(count_stmt) or 0)

        offset = (page - 1) * size
        stmt = stmt.offset(offset).limit(size).order_by(CandidateModel.created_at.desc())
        return list(await self.session.scalars(stmt)), total

    async def candidate_count(self, start_time: datetime, end_time: datetime):
        stmt = select(
            func.date(CandidateModel.created_at),
            func.count(CandidateModel.id)
        ).where(
            and_(
                CandidateModel.created_at >= start_time,
                CandidateModel.created_at <= end_time
            )
        ).group_by(
            func.date(CandidateModel.created_at),
        ).order_by(
            func.date(CandidateModel.created_at)
        )
        return (await self.session.execute(stmt)).all()
    async def list_visible_by_ids(
        self,
        *,
        candidate_ids: list[str],
        current_user: UserModel,
    ) -> list[CandidateModel]:
        """按候选人ID列表查询，并做 PostgreSQL 权限复核。"""

        if not candidate_ids:
            return []

        stmt = (
            select(CandidateModel)
            .where(CandidateModel.id.in_(candidate_ids))
            .options(
                selectinload(CandidateModel.position).selectinload(PositionModel.department),
                selectinload(CandidateModel.position).selectinload(PositionModel.creator),
                selectinload(CandidateModel.resume).selectinload(ResumeModel.uploader),
                selectinload(CandidateModel.creator),
                selectinload(CandidateModel.ai_score),
            )
        )

        stmt = CandidatePolicy.apply_sql_scope(
            stmt,
            CandidatePolicy.resolve_scope(current_user),
        )

        result = await self.session.scalars(stmt)
        candidates = list(result)

        # 按 Milvus 召回顺序返回，避免 SQL 查询打乱排序。
        order_map = {candidate_id: index for index, candidate_id in enumerate(candidate_ids)}
        return sorted(candidates, key=lambda c: order_map.get(c.id, 999999))



class CandidateAIScoreRepo(BaseRepo):
    async def create_candidate_score(self, candidate_id: str, candidate_score_dict: dict):
        candidate_score = CandidateAIScoreModel(**candidate_score_dict, candidate_id=candidate_id)
        self.session.add(candidate_score)
        return candidate_score

    async def get_by_candidate_id(self, candidate_id: str):
        return await self.session.scalar(select(CandidateAIScoreModel).where(CandidateAIScoreModel.candidate_id==candidate_id).options(selectinload(CandidateAIScoreModel.candidate)))

    async def update_candidate_status(self, candidate_id: str, status: CandidateStatusEnum):
        candidate_score = self.get_by_candidate_id(candidate_id)
        candidate_score.status = status
