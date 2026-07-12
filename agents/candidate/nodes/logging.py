import asyncio
import functools
import inspect
import time
from collections.abc import Awaitable, Callable
from typing import Any

from loguru import logger

from services.candidate_agent_event_service import CandidateAgentEventService

from .context import get_state_value


def _format_value(value: Any) -> str | None:
    """将枚举等值转成适合日志展示的短文本。"""
    if value is None:
        return None
    if hasattr(value, "value"):
        return str(value.value)
    return str(value)


def _jsonable_summary(value: Any) -> Any:
    """递归转换为 JSON 字段可保存的简单结构。"""
    if value is None or isinstance(value, str | int | float | bool):
        return value
    if hasattr(value, "value"):
        return value.value
    if isinstance(value, dict):
        return {key: _jsonable_summary(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_jsonable_summary(item) for item in value]
    return str(value)


def build_graph_log_payload(state: Any, extra: dict[str, Any] | None = None) -> dict:
    """提取候选人 Graph 的轻量日志字段，避免打印邮件正文/简历正文。"""
    payload = {
        "thread_id": get_state_value(state, "thread_id"),
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


def _event_status_from_update(update: dict | None) -> str:
    """根据节点输出推断业务审计状态。"""
    if not update:
        return "succeeded"
    if update.get("need_human_review"):
        return "need_human_review"
    return "succeeded"


def _event_data_from_payload(
    *,
    payload: dict,
    node_name: str,
    action_type: str,
    status: str,
    route_decision: str | None = None,
    output_summary: dict | None = None,
    error_message: str | None = None,
    duration_ms: int | None = None,
) -> dict:
    """将日志 payload 转换为 candidate_agent_events 表字段。"""
    return {
        "thread_id": payload.get("thread_id"),
        "candidate_id": payload.get("candidate_id"),
        "position_id": payload.get("position_id"),
        "interviewer_id": payload.get("interviewer_id"),
        "event_type": payload.get("event_type"),
        "node_name": node_name,
        "action_type": action_type,
        "status": status,
        "stage_before": payload.get("stage"),
        "stage_after": _format_value((output_summary or {}).get("stage"))
        or payload.get("stage"),
        "route_decision": route_decision,
        "duration_ms": duration_ms,
        "input_summary": _jsonable_summary(payload),
        "output_summary": _jsonable_summary(output_summary),
        "error_message": error_message,
    }


async def record_graph_event(event_data: dict) -> None:
    """写入 Graph 业务审计事件；失败不影响主流程。"""
    try:
        await CandidateAgentEventService().record_event(event_data)
    except Exception as exc:
        logger.warning(
            "[candidate_graph] record event failed action_type={} node={} error={}",
            event_data.get("action_type"),
            event_data.get("node_name"),
            exc,
        )


def log_node(
    node_name: str,
    node_func: Callable[[Any], dict | Awaitable[dict]],
) -> Callable[[Any], Awaitable[dict]]:
    """包装 Graph 节点，记录进入、退出和异常。

    日志统一写入现有 loguru sink，因此默认进入 log/app.log。
    """

    @functools.wraps(node_func)
    async def wrapper(state: Any) -> dict:
        started_at = time.perf_counter()
        enter_payload = build_graph_log_payload(state)
        logger.info(
            "[candidate_graph] enter node={} payload={}",
            node_name,
            enter_payload,
        )
        await record_graph_event(
            _event_data_from_payload(
                payload=enter_payload,
                node_name=node_name,
                action_type="node_enter",
                status="started",
            )
        )
        try:
            result = node_func(state)
            if inspect.isawaitable(result):
                result = await result
            duration_ms = int((time.perf_counter() - started_at) * 1000)
            exit_payload = build_graph_log_payload(state, result)
            logger.info(
                "[candidate_graph] exit node={} update={} payload={}",
                node_name,
                result,
                exit_payload,
            )
            await record_graph_event(
                _event_data_from_payload(
                    payload=enter_payload,
                    node_name=node_name,
                    action_type="node_exit",
                    status=_event_status_from_update(result),
                    output_summary=result,
                    error_message=result.get("last_error") if result else None,
                    duration_ms=duration_ms,
                )
            )
            return result
        except Exception as exc:
            duration_ms = int((time.perf_counter() - started_at) * 1000)
            logger.exception(
                "[candidate_graph] error node={} payload={} error={}",
                node_name,
                enter_payload,
                exc,
            )
            await record_graph_event(
                _event_data_from_payload(
                    payload=enter_payload,
                    node_name=node_name,
                    action_type="node_error",
                    status="failed",
                    error_message=str(exc),
                    duration_ms=duration_ms,
                )
            )
            raise

    return wrapper


async def record_graph_route(route_name: str, state: Any, decision: str) -> None:
    """写入条件边路由审计事件。"""
    payload = build_graph_log_payload(state)
    await record_graph_event(
        _event_data_from_payload(
            payload=payload,
            node_name=route_name,
            action_type="route",
            status="routed",
            route_decision=decision,
        )
    )


def log_route(route_name: str, state: Any, decision: str) -> None:
    """记录条件边路由选择。"""
    payload = build_graph_log_payload(state)
    logger.info(
        "[candidate_graph] route name={} decision={} payload={}",
        route_name,
        decision,
        payload,
    )
    try:
        asyncio.get_running_loop().create_task(
            record_graph_route(route_name, state, decision)
        )
    except RuntimeError:
        # 单元测试或同步上下文中没有事件循环时，只保留文件日志。
        return
