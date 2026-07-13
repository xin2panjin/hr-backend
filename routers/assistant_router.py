"""HR 招聘助手的会话管理接口。"""

import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse

from dependencies import get_hr_assistant_user
from models.assistant_conversation import AssistantConversationStatusEnum
from models.user import UserModel
from schemas.assistant_conversation_schema import (
    AssistantConversationListRespSchema,
    AssistantConversationSchema,
    AssistantMessageListRespSchema,
    AssistantMessageSchema,
    CreateAssistantConversationReqSchema,
    CreateAssistantConversationRespSchema,
    SendAssistantMessageReqSchema,
    SendAssistantMessageRespSchema,
    UpdateAssistantConversationReqSchema,
)
from services.hr_assistant_conversation_service import (
    AssistantConversationInactiveError,
    AssistantConversationNotFoundError,
    HRAssistantConversationService,
)

router = APIRouter(prefix="/assistant", tags=["hr-assistant"])


def _conversation_schema(conversation) -> AssistantConversationSchema:
    """将 ORM 会话转换为接口响应。"""

    return AssistantConversationSchema(
        id=conversation.id,
        title=conversation.title,
        status=getattr(conversation.status, "value", conversation.status),
        last_message_at=conversation.last_message_at,
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
    )


def _message_schema(message) -> AssistantMessageSchema:
    """返回用户和助手消息；工具审计记录不直接暴露给前端。"""

    metadata = message.message_metadata or {}
    return AssistantMessageSchema(
        id=message.id,
        role=getattr(message.role, "value", message.role),
        content=message.content,
        artifacts=metadata.get("artifacts", []),
        created_at=message.created_at,
    )


def _raise_service_error(exc: Exception) -> None:
    """统一把业务异常映射成不泄露会话信息的 HTTP 响应。"""

    if isinstance(exc, AssistantConversationNotFoundError):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="会话不存在") from exc
    if isinstance(exc, AssistantConversationInactiveError):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    raise exc


def _format_sse(event: str, data: dict) -> str:
    """序列化标准 SSE 事件，确保中文内容不被转义。"""

    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.post("/conversations", response_model=CreateAssistantConversationRespSchema, summary="创建招聘助手会话")
async def create_conversation(
    data: CreateAssistantConversationReqSchema,
    current_user: UserModel = Depends(get_hr_assistant_user),
):
    conversation = await HRAssistantConversationService().create_conversation(
        user_id=current_user.id,
        title=data.title.strip(),
    )
    return {"conversation": _conversation_schema(conversation)}


@router.get("/conversations", response_model=AssistantConversationListRespSchema, summary="获取我的招聘助手会话")
async def list_conversations(
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
    current_user: UserModel = Depends(get_hr_assistant_user),
):
    conversations, total = await HRAssistantConversationService().list_conversations(
        user_id=current_user.id,
        page=page,
        size=size,
    )
    return {
        "items": [_conversation_schema(item) for item in conversations],
        "total": total,
        "page": page,
        "size": size,
    }


@router.get(
    "/conversations/{conversation_id}/messages",
    response_model=AssistantMessageListRespSchema,
    summary="获取招聘助手会话历史",
)
async def list_conversation_messages(
    conversation_id: str,
    current_user: UserModel = Depends(get_hr_assistant_user),
):
    try:
        messages = await HRAssistantConversationService().list_messages(
            user_id=current_user.id,
            conversation_id=conversation_id,
        )
    except (AssistantConversationNotFoundError, AssistantConversationInactiveError) as exc:
        _raise_service_error(exc)
    return {"items": [_message_schema(item) for item in messages]}


@router.post(
    "/conversations/{conversation_id}/messages",
    response_model=SendAssistantMessageRespSchema,
    summary="发送招聘助手消息",
)
async def send_conversation_message(
    conversation_id: str,
    data: SendAssistantMessageReqSchema,
    current_user: UserModel = Depends(get_hr_assistant_user),
):
    try:
        return await HRAssistantConversationService().send_message(
            user_id=current_user.id,
            conversation_id=conversation_id,
            content=data.content.strip(),
        )
    except (AssistantConversationNotFoundError, AssistantConversationInactiveError) as exc:
        _raise_service_error(exc)


@router.post(
    "/conversations/{conversation_id}/messages/stream",
    summary="流式发送招聘助手消息",
    response_class=StreamingResponse,
)
async def stream_conversation_message(
    conversation_id: str,
    data: SendAssistantMessageReqSchema,
    request: Request,
    current_user: UserModel = Depends(get_hr_assistant_user),
):
    """输出模型文本和工具过程；最终回答仍由 Service 统一持久化。"""

    service = HRAssistantConversationService()
    try:
        # StreamingResponse 一旦开始写入就无法再返回 HTTP 404/409，因此预校验。
        await service.ensure_active_conversation(
            user_id=current_user.id,
            conversation_id=conversation_id,
        )
    except (AssistantConversationNotFoundError, AssistantConversationInactiveError) as exc:
        _raise_service_error(exc)

    async def event_source() -> AsyncIterator[str]:
        async for event in service.stream_message(
            user_id=current_user.id,
            conversation_id=conversation_id,
            content=data.content.strip(),
        ):
            if await request.is_disconnected():
                return
            yield _format_sse(event["event"], event["data"])

    return StreamingResponse(
        event_source(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.patch(
    "/conversations/{conversation_id}",
    response_model=AssistantConversationSchema,
    summary="重命名或归档招聘助手会话",
)
async def update_conversation(
    conversation_id: str,
    data: UpdateAssistantConversationReqSchema,
    current_user: UserModel = Depends(get_hr_assistant_user),
):
    try:
        conversation = await HRAssistantConversationService().update_conversation(
            user_id=current_user.id,
            conversation_id=conversation_id,
            title=data.title.strip() if data.title is not None else None,
            status=(
                AssistantConversationStatusEnum(data.status)
                if data.status is not None
                else None
            ),
        )
    except (AssistantConversationNotFoundError, AssistantConversationInactiveError) as exc:
        _raise_service_error(exc)
    return _conversation_schema(conversation)


@router.delete(
    "/conversations/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT, summary="删除招聘助手会话")
async def delete_conversation(
    conversation_id: str,
    current_user: UserModel = Depends(get_hr_assistant_user),
):
    try:
        await HRAssistantConversationService().delete_conversation(
            user_id=current_user.id,
            conversation_id=conversation_id,
        )
    except (AssistantConversationNotFoundError, AssistantConversationInactiveError) as exc:
        _raise_service_error(exc)
