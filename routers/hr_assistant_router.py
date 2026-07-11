import json
from typing import Any

from shortuuid import uuid
from fastapi import APIRouter, Depends
from loguru import logger

from agents.hr_assistant.agent import HRAssistantAgent
from dependencies import get_current_user
from models.user import UserModel
from schemas.hr_assistant_schema import (
    HRAssistantChatReqSchema,
    HRAssistantChatRespSchema,
)

router = APIRouter(prefix="/hr-assistant", tags=["hr-assistant"])

def _to_status_text(status: Any) -> str | None:
    """把候选人状态统一转换成中文文本。"""

    if status is None:
        return None

    return getattr(status, "value", status)


def _build_open_candidate_detail_action(candidate_id: str) -> dict:
    """构造前端打开候选人详情的动作。"""

    return {
        "type": "open_candidate_detail",
        "label": "查看详情",
        "candidate_id": candidate_id,
    }


def _build_candidate_card(candidate: dict) -> dict | None:
    """把工具返回的候选人数据转换成前端候选人卡片。

    同时兼容 search_talent_pool 和 get_candidate_detail 两种工具返回结构。
    """

    candidate_id = candidate.get("candidate_id")
    if not candidate_id:
        return None

    position = candidate.get("position") or {}

    return {
        "candidate_id": candidate_id,
        "name": candidate.get("name"),
        "position_title": candidate.get("position_title") or position.get("title"),
        "status": _to_status_text(candidate.get("status")),
        "score": candidate.get("score"),
        "summary": (
            candidate.get("profile_text")
            or (candidate.get("ai_score") or {}).get("summary")
        ),
        "actions": [
            _build_open_candidate_detail_action(candidate_id),
        ],
    }


def _parse_tool_json_content(content: Any) -> dict | None:
    """解析 ToolMessage 的 JSON 内容。

    工具有时会返回普通错误文本，例如“没有找到符合条件的候选人”，这种情况直接忽略。
    """

    if not isinstance(content, str):
        return None

    try:
        payload = json.loads(content)
    except json.JSONDecodeError:
        return None

    return payload if isinstance(payload, dict) else None

def _get_current_turn_messages(messages: list[Any]) -> list[Any]:
    """只取当前轮次的消息（从最后一条用户消息之后开始）。"""

    last_user_index = -1
    for index, message in enumerate(messages):
        if getattr(message, "type", None) in {"human", "user"}:
            last_user_index = index

    if last_user_index == -1:
        return messages

    return messages[last_user_index + 1 :]

def _extract_hr_assistant_artifacts(messages: list[Any]) -> list[dict]:
    """从 Agent 消息中提取前端可渲染的结构化产物。"""

    artifacts: list[dict] = []

    for message in messages:
        # LangChain 的工具消息一般 type == "tool"。
        if getattr(message, "type", None) != "tool":
            continue

        payload = _parse_tool_json_content(getattr(message, "content", None))
        if not payload:
            continue

        # search_talent_pool 返回结构：
        # {"candidates": [...], "count": n}
        artifact_type = payload.get("artifact_type")
        if artifact_type == "candidate_cards":
            cards = [
                card
                for candidate in payload["candidates"]
                if (card := _build_candidate_card(candidate)) is not None
            ]

            if cards:
                artifacts.append(
                    {
                        "type": "candidate_cards",
                        "title": "候选人搜索结果",
                        "candidates": cards,
                        "raw": payload,
                    }
                )

            continue

        # get_candidate_detail 返回结构：
        # {"candidate_id": "...", "name": "...", "position": {...}, ...}
        if artifact_type == "candidate_detail":
            card = _build_candidate_card(payload)
            if card:
                artifacts.append(
                    {
                        "type": "candidate_detail",
                        "title": "候选人详情",
                        "candidates": [card],
                        "raw": payload,
                    }
                )
        # compare_candidates 返回结构：
        # {"artifact_type": "candidate_comparison", "candidates": [...], ...}
        if artifact_type == "candidate_comparison":
            cards = [
                card
                for candidate in payload.get("candidates", [])
                if (card := _build_candidate_card(candidate)) is not None
            ]

            if cards:
                artifacts.append(
                    {
                        "type": "candidate_comparison",
                        "title": "候选人对比结果",
                        "candidates": cards,
                        # 保留完整详情、AI 评分和未找到的候选人 ID，
                        # 前端对比表将从这里读取。
                        "raw": payload,
                    }
                )

            continue
    # 同一轮里如果 AI 多次调用 search_talent_pool，只保留最后一次搜索结果
    search_card_indexes = [
        index
        for index, artifact in enumerate(artifacts)
        if artifact["type"] == "candidate_cards"
    ]
    if len(search_card_indexes) > 1:
        last_index = search_card_indexes[-1]
        artifacts = [
            artifact
            for index, artifact in enumerate(artifacts)
            if artifact["type"] != "candidate_cards" or index == last_index
        ]
    return artifacts

@router.post("/chat", summary="HR招聘助手对话", response_model=HRAssistantChatRespSchema)
async def chat_with_hr_assistant(
    chat_data: HRAssistantChatReqSchema,
    current_user: UserModel = Depends(get_current_user),
):
    conversation_id = chat_data.conversation_id or uuid()
    thread_id = f"hr-assistant:{current_user.id}:{conversation_id}"
    logger.info(
        f"HR助手请求：user_id={current_user.id}, conversation_id={conversation_id}, message={chat_data.message}"
    )
    async with HRAssistantAgent(current_user_id=current_user.id) as agent:
        response = await agent.ainvoke(
            messages=[
                {
                    "role": "user",
                    "content": chat_data.message,
                }
            ],
            thread_id=thread_id,
        )

    messages = response.get("messages", [])
    answer = messages[-1].content if messages else ""
    artifacts = _extract_hr_assistant_artifacts(_get_current_turn_messages(messages))

    logger.info(
        f"HR助手响应：user_id={current_user.id}, "
        f"conversation_id={conversation_id}, artifacts_count={len(artifacts)}"
    )
    return {
        "conversation_id": conversation_id,
        "answer": answer,
        "artifacts": artifacts,
    }