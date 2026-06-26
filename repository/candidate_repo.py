from datetime import datetime

from models.positions import PositionModel
from . import BaseRepo
from models.candidate import ResumeModel, CandidateModel
from sqlalchemy import select, update
from models.candidate import CandidateAIScoreModel
from sqlalchemy.orm import selectinload
from models.candidate import CandidateStatusEnum
from models.user import UserModel
from sqlalchemy import func, and_


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
                selectinload(CandidateModel.creator)
            )
        )

    async def get_list(
        self,
        current_user: UserModel,
        position_id: str|None = None,
        status: CandidateStatusEnum|None = None,
        page: int = 1,
        size: int = 10
    ):
        stmt = select(CandidateModel)
        # 按照用户的角色来查找数据
        # 1. 如果是superuser，那么可以获取所有的候选人
        # 2. 如果是hr，那么可以获取所负责部门的候选人
        # 3. 如果是部门成员，那么可以获取自己发布的职位的候选人
        if current_user.is_superuser:
            pass
        elif current_user.is_hr:
            hr_user = await self.session.scalar(
                select(UserModel)
                .where(UserModel.id == current_user.id)
                .options(selectinload(UserModel.managed_departments))
            )
            # 提取hr所负责的部门的id
            managed_department_ids = [
                d.id for d in hr_user.managed_departments
            ]
            if len(managed_department_ids) == 0:
                return []
            # 用连接的形式过滤候选人
            stmt = stmt.join(PositionModel).where(PositionModel.department_id.in_(managed_department_ids))
        else:
            # 普通成员
            stmt = stmt.join(PositionModel).where(PositionModel.creator_id == current_user.id)

        if position_id is not None:
            stmt = stmt.where(CandidateModel.position_id == position_id)

        if status is not None:
            stmt = stmt.where(CandidateModel.status == status)

        offset = (page - 1) * size
        stmt = stmt.offset(offset).limit(size).order_by(CandidateModel.created_at.desc())
        return await self.session.scalars(stmt)

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
