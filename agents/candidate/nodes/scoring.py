from typing import Any

from langchain.agents import create_agent
from langchain.agents.middleware import ModelFallbackMiddleware
from langchain_core.prompts import PromptTemplate

from agents.llms import deepseek_llm, qwen_llm
from schemas.agent_schema import AgentCandidateScoreSchema
from services.candidate_scoring_service import CandidateScoringService

from ..prompts import (
    SCORE_FOR_CANDIDATE_SYSTEM_PROMPT,
    SCORE_FOR_CANDIDATE_USER_PROMPT,
)
from ..state import CandidateProcessStage
from .context import get_state_value, load_candidate_runtime_context


# 评分 Agent 只负责生成结构化评分；业务落库由 CandidateScoringService 处理。
score_agent = create_agent(
    model=qwen_llm,
    system_prompt=SCORE_FOR_CANDIDATE_SYSTEM_PROMPT,
    middleware=[ModelFallbackMiddleware(first_model=deepseek_llm)],
    response_format=AgentCandidateScoreSchema,
)


async def generate_candidate_score(state: Any) -> AgentCandidateScoreSchema:
    """按轻量 State 加载上下文，并调用评分 LLM 生成结构化评分。"""
    context = await load_candidate_runtime_context(state)
    prompt = PromptTemplate.from_template(SCORE_FOR_CANDIDATE_USER_PROMPT).invoke(
        {
            "candidate": context.candidate.model_dump_json(),
            "position": context.position.model_dump_json(),
        }
    )
    response = await score_agent.ainvoke(
        {"messages": [{"role": "user", "content": prompt.text}]}
    )
    return response["structured_response"]


async def score_candidate_node(state: Any) -> dict:
    """候选人创建后执行 AI 评分，并把轻量评分结论写回 Graph State。"""
    candidate_id = get_state_value(state, "candidate_id")
    if not candidate_id:
        return {
            "stage": CandidateProcessStage.NEED_HUMAN_REVIEW,
            "need_human_review": True,
            "last_error": "候选人评分失败：流程缺少 candidate_id",
        }

    try:
        score = await generate_candidate_score(state)
        await CandidateScoringService().save_score(candidate_id, score)
        return {
            "stage": CandidateProcessStage.SCORED,
            # 当前招聘 Prompt 的业务规则是综合分超过 6 分进入邀约。
            "score_passed": score.overall_score > 6,
            "overall_score": score.overall_score,
            "score_summary": score.summary,
            "last_error": None,
            "need_human_review": False,
        }
    except Exception as exc:
        return {
            "stage": CandidateProcessStage.NEED_HUMAN_REVIEW,
            "need_human_review": True,
            "last_error": f"候选人评分失败：{exc}",
        }
