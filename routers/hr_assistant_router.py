"""旧版 HR 助手聊天接口。

前端迁移到 ``/assistant/conversations`` 前保留该入口。它不再自行管理
LangGraph thread，而是统一复用会话服务，避免旧、新接口产生两套历史数据。
"""

from fastapi import APIRouter, Depends, HTTPException, status

from dependencies import get_hr_assistant_user
from models.user import UserModel
from schemas.hr_assistant_schema import (
    HRAssistantChatReqSchema,
    HRAssistantChatRespSchema,
)
from services.hr_assistant_conversation_service import (
    AssistantConversationInactiveError,
    AssistantConversationNotFoundError,
    HRAssistantConversationService,
)

router = APIRouter(prefix="/hr-assistant", tags=["hr-assistant"])


def _get_current_turn_messages(messages):
    """兼容已有单元测试，实际逻辑由会话服务统一维护。"""

    return HRAssistantConversationService._get_current_turn_messages(messages)


def _extract_hr_assistant_artifacts(messages):
    """兼容旧接口的产物格式，保留 ``raw`` 供旧前端的对比卡使用。"""

    service = HRAssistantConversationService()
    artifacts = service._extract_artifacts(messages)
    raw_payloads = []
    for message in messages:
        if getattr(message, "type", None) != "tool":
            continue
        if payload := service._parse_tool_payload(getattr(message, "content", None)):
            raw_payloads.append(payload)

    for artifact in artifacts:
        for payload in raw_payloads:
            if payload.get("artifact_type") == artifact["type"]:
                artifact["raw"] = payload
                break
    return artifacts


@router.post("/chat", summary="HR招聘助手对话（兼容旧接口）", response_model=HRAssistantChatRespSchema)
async def chat_with_hr_assistant(
    chat_data: HRAssistantChatReqSchema,
    current_user: UserModel = Depends(get_hr_assistant_user),
):
    """兼容旧页面；未传会话 ID 时自动创建一条业务会话。"""

    service = HRAssistantConversationService()
    conversation_id = chat_data.conversation_id
    if conversation_id is None:
        conversation = await service.create_conversation(user_id=current_user.id)
        conversation_id = conversation.id

    try:
        result = await service.send_message(
            user_id=current_user.id,
            conversation_id=conversation_id,
            content=chat_data.message.strip(),
        )
    except AssistantConversationNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="会话不存在") from exc
    except AssistantConversationInactiveError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    return {
        "conversation_id": result["conversation_id"],
        "answer": result["answer"],
        "artifacts": result["artifacts"],
    }
