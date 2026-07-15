"""候选人公开门户接口。"""

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status

from core.cache import HRCache
from dependencies import get_cache_instance, get_session_instance
from dependencies.candidate_portal import get_candidate_portal_email
from models import AsyncSession
from schemas.candidate_communication_schema import (
    CandidateMessageSchema, CandidatePortalSendCodeSchema, CandidatePortalSendMessageSchema,
    CandidatePortalVerifyCodeSchema,
)
from services.candidate_communication_service import CandidateCommunicationNotFoundError, CandidateCommunicationService
from services.candidate_portal_auth_service import CandidatePortalAuthService
from tasks.candidate_portal_email_tasks import send_candidate_portal_code_email_task
from models.candidate_communication import CandidateConversationModel
from sqlalchemy import select

router = APIRouter(prefix="/candidate-portal", tags=["candidate-portal"])


def _message_schema(message) -> dict:
    return CandidateMessageSchema(
        id=message.id, sender_type=getattr(message.sender_type, "value", message.sender_type),
        content=message.content, sender_name=None,
        created_at=message.created_at,
    ).model_dump()


@router.post("/auth/code", summary="发送候选人登录验证码")
async def send_login_code(
    data: CandidatePortalSendCodeSchema,
    background_tasks: BackgroundTasks,
    cache: HRCache = Depends(get_cache_instance),
):
    service = CandidatePortalAuthService()
    code = await service.send_code(email=str(data.email), cache=cache)
    background_tasks.add_task(send_candidate_portal_code_email_task, str(data.email).lower(), code)
    return {"result": "success"}


@router.post("/auth/verify", summary="验证候选人登录验证码")
async def verify_login_code(
    data: CandidatePortalVerifyCodeSchema,
    cache: HRCache = Depends(get_cache_instance),
    session: AsyncSession = Depends(get_session_instance),
):
    async with session.begin():
        token = await CandidatePortalAuthService().verify_code(
            email=str(data.email), code=data.code, cache=cache, session=session
        )
    return {"access_token": token, "token_type": "bearer"}


@router.post("/auth/logout", summary="退出候选人门户")
async def logout(_: str = Depends(get_candidate_portal_email)):
    # token 为短期无状态令牌；前端删除本地 token 即完成退出。
    return {"result": "success"}


@router.get("/applications", summary="获取我的已投递职位")
async def list_applications(
    email: str = Depends(get_candidate_portal_email),
    session: AsyncSession = Depends(get_session_instance),
):
    applications = await CandidateCommunicationService(session).list_portal_applications(email)
    conversation_ids = {
        conversation.candidate_id: conversation
        for conversation in await session.scalars(select(CandidateConversationModel).where(
            CandidateConversationModel.candidate_id.in_([item.id for item in applications])
        ))
    }
    return {"items": [{
        "candidate_id": item.id,
        "candidate_name": item.name,
        "position_title": item.position.title,
        "status": getattr(item.status, "value", item.status),
        "applied_at": item.created_at,
        "conversation_id": getattr(conversation_ids.get(item.id), "id", None),
        "last_message_at": getattr(conversation_ids.get(item.id), "last_message_at", None),
    } for item in applications]}


@router.get("/applications/{candidate_id}/messages", summary="获取候选人会话消息")
async def list_messages(
    candidate_id: str,
    email: str = Depends(get_candidate_portal_email),
    session: AsyncSession = Depends(get_session_instance),
):
    try:
        _, messages, conversation = await CandidateCommunicationService(session).list_messages_for_portal(
            candidate_id=candidate_id, email=email
        )
    except CandidateCommunicationNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="投递记录不存在") from exc
    return {"conversation_id": conversation.id if conversation else None, "items": [_message_schema(item) for item in messages]}


@router.post("/applications/{candidate_id}/messages", summary="候选人发送消息")
async def send_message(
    candidate_id: str,
    data: CandidatePortalSendMessageSchema,
    background_tasks: BackgroundTasks,
    email: str = Depends(get_candidate_portal_email),
    session: AsyncSession = Depends(get_session_instance),
):
    try:
        async with session.begin():
            message = await CandidateCommunicationService(session).send_portal_message(
                candidate_id=candidate_id, email=email, content=data.content
            )
    except CandidateCommunicationNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="投递记录不存在") from exc
    return {"message": _message_schema(message)}
