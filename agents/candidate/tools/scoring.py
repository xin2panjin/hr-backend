from langchain.tools import ToolRuntime, tool

from schemas.agent_schema import AgentCandidateScoreSchema
from services.candidate_scoring_service import CandidateScoringService

from ..nodes.context import get_state_value
from ..nodes.scoring import generate_candidate_score
from ..state import CandidateAgentState


@tool
async def score_for_candidate(runtime: ToolRuntime[CandidateAgentState]) -> str:
    """根据职位要求给候选人评分，并保存评分结果和筛选状态。"""
    score: AgentCandidateScoreSchema = await generate_candidate_score(runtime.state)
    # 数据库写入由 Service 统一处理，工具层只负责模型调用和参数传递。
    await CandidateScoringService().save_score(
        get_state_value(runtime.state, "candidate_id"),
        score,
    )
    return f"得分工具执行成功！该候选人得分为：{score.model_dump_json()}"
