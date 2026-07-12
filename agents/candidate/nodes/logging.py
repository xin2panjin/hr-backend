import functools
import inspect
from collections.abc import Awaitable, Callable
from typing import Any

from loguru import logger

from .context import get_state_value


def _format_value(value: Any) -> str | None:
    """将枚举等值转成适合日志展示的短文本。"""
    if value is None:
        return None
    if hasattr(value, "value"):
        return str(value.value)
    return str(value)


def build_graph_log_payload(state: Any, extra: dict[str, Any] | None = None) -> dict:
    """提取候选人 Graph 的轻量日志字段，避免打印邮件正文/简历正文。"""
    payload = {
        "candidate_id": get_state_value(state, "candidate_id"),
        "position_id": get_state_value(state, "position_id"),
        "interviewer_id": get_state_value(state, "interviewer_id"),
        "event_type": _format_value(get_state_value(state, "event_type")),
        "stage": _format_value(get_state_value(state, "stage")),
        "score_passed": get_state_value(state, "score_passed"),
        "overall_score": get_state_value(state, "overall_score"),
        "reply_intent": _format_value(
            get_state_value(state, "candidate_reply_intent")
        ),
        "requested_time": get_state_value(state, "candidate_requested_time"),
        "proposed_time": get_state_value(state, "proposed_interview_time"),
        "need_human_review": get_state_value(state, "need_human_review"),
        "last_error": get_state_value(state, "last_error"),
    }
    if extra:
        payload.update(extra)
    return {key: value for key, value in payload.items() if value is not None}


def log_node(
    node_name: str,
    node_func: Callable[[Any], dict | Awaitable[dict]],
) -> Callable[[Any], Awaitable[dict]]:
    """包装 Graph 节点，记录进入、退出和异常。

    日志统一写入现有 loguru sink，因此默认进入 log/app.log。
    """

    @functools.wraps(node_func)
    async def wrapper(state: Any) -> dict:
        logger.info(
            "[candidate_graph] enter node={} payload={}",
            node_name,
            build_graph_log_payload(state),
        )
        try:
            result = node_func(state)
            if inspect.isawaitable(result):
                result = await result
            logger.info(
                "[candidate_graph] exit node={} update={} payload={}",
                node_name,
                result,
                build_graph_log_payload(state, result),
            )
            return result
        except Exception as exc:
            logger.exception(
                "[candidate_graph] error node={} payload={} error={}",
                node_name,
                build_graph_log_payload(state),
                exc,
            )
            raise

    return wrapper


def log_route(route_name: str, state: Any, decision: str) -> None:
    """记录条件边路由选择。"""
    logger.info(
        "[candidate_graph] route name={} decision={} payload={}",
        route_name,
        decision,
        build_graph_log_payload(state),
    )
