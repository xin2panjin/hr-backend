import json

from langchain.tools import ToolRuntime, tool
from loguru import logger

from models import AsyncSessionFactory
from repository.candidate_repo import CandidateRepo
from repository.user_repo import UserRepo

from ..state import HRAssistantState
from .candidate_detail import _build_candidate_detail


def _build_candidate_compare_payload(candidates, requested_candidate_ids: list[str]) -> dict:
    """构造候选人对比工具返回结果。

    注意：
    1. 这里复用 _build_candidate_detail，保证不会返回手机号、邮箱、生日等敏感信息。
    2. missing_candidate_ids 用于告诉模型哪些候选人不存在或当前用户无权查看。
    """

    found_candidate_ids = {candidate.id for candidate in candidates}

    return {
        "candidates": [
            _build_candidate_detail(candidate)
            for candidate in candidates
        ],
        "count": len(candidates),
        "missing_candidate_ids": [
            candidate_id
            for candidate_id in requested_candidate_ids
            if candidate_id not in found_candidate_ids
        ],
    }


@tool
async def compare_candidates(
    candidate_ids: list[str],
    runtime: ToolRuntime[HRAssistantState],
) -> str:
    """根据候选人ID列表查询多个候选人的脱敏详情，用于候选人对比和面试优先级排序。

    参数：
    - candidate_ids: 候选人ID列表，通常来自 search_talent_pool 或 get_candidate_detail 的返回结果
    """

    current_user_id = runtime.state["current_user_id"]

    logger.info(
        f"调用候选人对比工具：user_id={current_user_id}, candidate_ids={candidate_ids}"
    )

    if not candidate_ids:
        return "请提供至少两个候选人ID。"

    # 去重但保留原始顺序，避免模型重复传同一个候选人ID。
    normalized_candidate_ids = list(dict.fromkeys(candidate_ids))

    if len(normalized_candidate_ids) < 2:
        return "候选人对比至少需要两个不同的候选人ID。"

    async with AsyncSessionFactory() as session:
        async with session.begin():
            user = await UserRepo(session).get_by_id(current_user_id)
            if not user:
                return "当前用户不存在，无法对比候选人。"

            candidates = await CandidateRepo(session).list_visible_by_ids(
                candidate_ids=normalized_candidate_ids,
                current_user=user,
            )

    if not candidates:
        return "没有找到可对比的候选人，或当前用户无权查看这些候选人。"

    payload = _build_candidate_compare_payload(
        candidates=candidates,
        requested_candidate_ids=normalized_candidate_ids,
    )

    logger.info(
        f"候选人对比工具完成：user_id={current_user_id}, "
        f"requested_count={len(normalized_candidate_ids)}, found_count={len(candidates)}"
    )

    return json.dumps(
        payload,
        ensure_ascii=False,
        default=str,
    )