from langchain.agents import create_agent
from langchain.agents.middleware import ModelFallbackMiddleware
from langchain.tools import ToolRuntime, tool
from langchain_core.prompts import PromptTemplate

from agents.llms import deepseek_llm, qwen_llm
from schemas.agent_schema import AgentCandidateScoreSchema
from schemas.candidate_schema import CandidateSchema
from schemas.position_schema import PositionSchema
from services.candidate_scoring_service import CandidateScoringService

from ..prompts import (
    SCORE_FOR_CANDIDATE_SYSTEM_PROMPT,
    SCORE_FOR_CANDIDATE_USER_PROMPT,
)
from ..state import CandidateAgentState


# 评分 Agent 只负责生成符合 Schema 的结构化评分，不直接修改业务数据。
score_agent = create_agent(
    model=qwen_llm,
    system_prompt=SCORE_FOR_CANDIDATE_SYSTEM_PROMPT,
    middleware=[ModelFallbackMiddleware(first_model=deepseek_llm)],
    response_format=AgentCandidateScoreSchema,
)


@tool
async def score_for_candidate(runtime: ToolRuntime[CandidateAgentState]) -> str:
    """根据职位要求给候选人评分，并保存评分结果和筛选状态。"""
    candidate: CandidateSchema = runtime.state["candidate"]
    position: PositionSchema = runtime.state["position"]

    prompt = PromptTemplate.from_template(SCORE_FOR_CANDIDATE_USER_PROMPT).invoke(
        {
            "candidate": candidate.model_dump_json(),
            "position": position.model_dump_json(),
        }
    )
    # response_format 会校验评分字段及1到10分的取值范围。
    response = await score_agent.ainvoke(
        {"messages": [{"role": "user", "content": prompt.text}]}
    )
    score: AgentCandidateScoreSchema = response["structured_response"]
    # 数据库写入由 Service 统一处理，工具层只负责模型调用和参数传递。
    await CandidateScoringService().save_score(candidate.id, score)
    return f"得分工具执行成功！该候选人得分为：{score.model_dump_json()}"
