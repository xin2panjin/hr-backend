import json
from loguru import logger
from langchain.tools import ToolRuntime, tool

from models import AsyncSessionFactory
from repository.candidate_repo import CandidateRepo
from repository.user_repo import UserRepo

from ..state import HRAssistantState


def _safe_text(value: str | None) -> str:
    """把空字段统一转成空字符串，避免工具返回 None 影响模型理解。"""

    return value or ""


def _build_candidate_detail(candidate) -> dict:
    """把候选人 ORM 对象转换成适合 Agent 使用的脱敏详情。"""

    ai_score = candidate.ai_score

    return {
        "candidate_id": candidate.id,
        "name": candidate.name,
        "gender": candidate.gender.value if candidate.gender else None,
        "status": candidate.status.value if candidate.status else None,
        # 默认不返回手机号、邮箱、生日，避免对话中泄露敏感信息。
        "position": {
            "id": candidate.position.id if candidate.position else None,
            "title": candidate.position.title if candidate.position else None,
            "department": (
                candidate.position.department.name
                if candidate.position and candidate.position.department
                else None
            ),
            "requirements": (
                _safe_text(candidate.position.requirements)
                if candidate.position
                else ""
            ),
        },
        "profile": {
            "skills": _safe_text(candidate.skills),
            "work_experience": _safe_text(candidate.work_experience),
            "project_experience": _safe_text(candidate.project_experience),
            "education_experience": _safe_text(candidate.education_experience),
            "self_evaluation": _safe_text(candidate.self_evaluation),
            "other_information": _safe_text(candidate.other_information),
        },
        "ai_score": None
        if not ai_score
        else {
            "overall_score": ai_score.overall_score,
            "summary": ai_score.summary,
            "strengths": ai_score.strengths,
            "weaknesses": ai_score.weaknesses,
            "work_experience_score": ai_score.work_experience_score,
            "technical_skills_score": ai_score.technical_skills_score,
            "soft_skills_score": ai_score.soft_skills_score,
            "educational_background_score": ai_score.educational_background_score,
            "project_experience_score": ai_score.project_experience_score,
        },
    }


@tool
async def get_candidate_detail(
    candidate_id: str,
    runtime: ToolRuntime[HRAssistantState],
) -> str:
    """根据候选人ID查询候选人详情。

    参数：
    - candidate_id: 候选人ID，通常来自 search_talent_pool 的返回结果
    """

    current_user_id = runtime.state["current_user_id"]
    logger.info(
        f"调用候选人详情工具：user_id={current_user_id}, candidate_id={candidate_id}"
    )

    async with AsyncSessionFactory() as session:
        async with session.begin():
            user = await UserRepo(session).get_by_id(current_user_id)
            if not user:
                return "当前用户不存在，无法查询候选人详情。"

            candidates = await CandidateRepo(session).list_visible_by_ids(
                candidate_ids=[candidate_id],
                current_user=user,
            )

    if not candidates:
        return "没有找到该候选人，或当前用户无权查看该候选人。"

    detail = _build_candidate_detail(candidates[0])
    detail["artifact_type"] = "candidate_detail"

    return json.dumps(
        detail,
        ensure_ascii=False,
        default=str,
    )