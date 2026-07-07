from schemas.agent_schema import AgentCandidateScoreSchema
from models import AsyncSessionFactory
from models.candidate import CandidateStatusEnum
from repository.candidate_repo import CandidateAIScoreRepo, CandidateRepo


class CandidateScoringService:
    """负责保存 AI 评分，并根据评分结果更新候选人筛选状态。"""

    async def save_score(
        self,
        candidate_id: str,
        score: AgentCandidateScoreSchema,
    ) -> CandidateStatusEnum:
        """在同一事务中写入评分，并将综合分转换为候选人状态。"""
        # 业务规则保持与招聘 Prompt 一致：只有综合分严格大于8分才通过。
        status = CandidateStatusEnum.AI_FILTER_REJECTED
        if score.overall_score > 8:
            status = CandidateStatusEnum.AI_FILTER_PASSED

        # 评分和候选人状态必须一起提交，避免出现评分已保存但状态未更新。
        async with AsyncSessionFactory() as session:
            async with session.begin():
                await CandidateAIScoreRepo(session).create_candidate_score(
                    candidate_id=candidate_id,
                    candidate_score_dict=score.model_dump(),
                )
                await CandidateRepo(session).update_candidate_status(
                    candidate_id=candidate_id,
                    status=status,
                )
        return status
