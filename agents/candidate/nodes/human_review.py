from typing import Any

from ..state import CandidateProcessStage
from .context import get_state_value


async def human_review_node(state: Any) -> dict:
    """人工处理占位节点。

    第一版只把流程状态标记为需要人工处理；后续可在这里创建人工待办。
    """
    return {
        "stage": CandidateProcessStage.NEED_HUMAN_REVIEW,
        "need_human_review": True,
        "last_error": get_state_value(state, "last_error") or "候选人流程需要人工处理",
    }
