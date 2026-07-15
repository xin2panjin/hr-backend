"""HR 候选人沟通工作台与待办中心接口。"""

from fastapi import APIRouter, Depends, HTTPException, Query, status

from dependencies import get_current_user, get_session_instance, require_permission
from iam.permissions import PermissionCode
from models import AsyncSession
from models.candidate_communication import CandidateFollowupTaskStatusEnum
from models.user import UserModel
from schemas.candidate_communication_schema import CreateFollowupTaskNoteSchema, HRSendMessageSchema, UpdateFollowupTaskSchema
from services.candidate_communication_service import CandidateCommunicationNotFoundError, CandidateCommunicationService

router = APIRouter(prefix="/candidate-communications", tags=["candidate-communications"])


def _message(item) -> dict:
    return {
        "id": item.id, "sender_type": getattr(item.sender_type, "value", item.sender_type),
        "content": item.content, "sender_name": None,
        "created_at": item.created_at,
    }


def _insight(item) -> dict | None:
    if not item:
        return None
    return {
        "id": item.id, "summary": item.summary, "stage": item.stage, "intent": item.intent,
        "confirmed_facts": item.confirmed_facts or [], "candidate_requests": item.candidate_requests or [],
        "hr_commitments": item.hr_commitments or [], "risks": item.risks or [],
        "next_step": item.next_step, "evidence": item.evidence or [], "created_at": item.created_at,
    }


def _task(item) -> dict:
    candidate = getattr(item, "_candidate", None) or getattr(item, "candidate", None)
    position = getattr(candidate, "position", None)
    assignee = getattr(item, "assignee", None)
    return {
        "id": item.id, "candidate_id": item.candidate_id, "conversation_id": item.conversation_id,
        "candidate_name": getattr(candidate, "name", None), "position_title": getattr(position, "title", None),
        "assignee_name": getattr(assignee, "username", None), "title": item.title, "task_type": item.task_type,
        "priority": getattr(item.priority, "value", item.priority), "status": getattr(item.status, "value", item.status),
        "due_at": item.due_at, "evidence": item.evidence or [], "created_at": item.created_at,
    }


def _raise_not_found(exc: Exception) -> None:
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="候选人沟通记录不存在或无权访问") from exc


@router.get("/conversations", summary="获取候选人沟通会话列表")
async def list_conversations(
    keyword: str | None = Query(default=None, max_length=100),
    current_user: UserModel = Depends(require_permission(PermissionCode.CANDIDATE_COMMUNICATION_USE)),
    session: AsyncSession = Depends(get_session_instance),
):
    items = await CandidateCommunicationService(session).list_hr_conversations(current_user=current_user, keyword=keyword)
    return {"items": [{
        "candidate_id": item.candidate_id, "conversation_id": item.id, "candidate_name": item.candidate.name,
        "candidate_email": item.candidate.email, "position_title": item.candidate.position.title,
        "last_message_at": item.last_message_at, "unread_count": unread,
    } for item, unread in items]}


@router.get("/conversations/{candidate_id}", summary="获取 HR 候选人沟通详情")
async def conversation_detail(
    candidate_id: str,
    current_user: UserModel = Depends(require_permission(PermissionCode.CANDIDATE_COMMUNICATION_USE)),
    session: AsyncSession = Depends(get_session_instance),
):
    try:
        conversation, messages, insight, analysis_status = await CandidateCommunicationService(session).hr_conversation_detail(
            candidate_id=candidate_id, current_user=current_user
        )
    except CandidateCommunicationNotFoundError as exc:
        _raise_not_found(exc)
    candidate = conversation.candidate
    return {"conversation_id": conversation.id, "candidate": {
        "id": candidate.id, "name": candidate.name, "email": candidate.email, "phone_number": candidate.phone_number,
        "status": getattr(candidate.status, "value", candidate.status), "position_title": candidate.position.title,
        "work_experience": candidate.work_experience, "education_experience": candidate.education_experience,
        "skills": candidate.skills, "ai_summary": getattr(candidate.ai_score, "summary", None),
    }, "messages": [_message(item) for item in messages], "insight": _insight(insight), "analysis_status": analysis_status}


@router.post("/conversations/{candidate_id}/messages", summary="HR 发送候选人消息")
async def send_hr_message(
    candidate_id: str,
    data: HRSendMessageSchema,
    current_user: UserModel = Depends(require_permission(PermissionCode.CANDIDATE_COMMUNICATION_USE)),
    session: AsyncSession = Depends(get_session_instance),
):
    try:
        async with session.begin():
            message = await CandidateCommunicationService(session).send_hr_message(
                candidate_id=candidate_id, current_user=current_user, content=data.content
            )
    except CandidateCommunicationNotFoundError as exc:
        _raise_not_found(exc)
    return {"message": _message(message)}


@router.post("/conversations/{candidate_id}/read", summary="标记负责人已读")
async def mark_read(
    candidate_id: str,
    current_user: UserModel = Depends(require_permission(PermissionCode.CANDIDATE_COMMUNICATION_USE)),
    session: AsyncSession = Depends(get_session_instance),
):
    try:
        async with session.begin():
            await CandidateCommunicationService(session).mark_read(candidate_id=candidate_id, current_user=current_user)
    except CandidateCommunicationNotFoundError as exc:
        _raise_not_found(exc)
    return {"result": "success"}


@router.get("/tasks", summary="获取 HR 待办列表")
async def list_tasks(
    task_status: CandidateFollowupTaskStatusEnum | None = Query(default=None, alias="status"),
    priority: str | None = Query(default=None), keyword: str | None = Query(default=None, max_length=100),
    current_user: UserModel = Depends(require_permission(PermissionCode.CANDIDATE_COMMUNICATION_USE)),
    session: AsyncSession = Depends(get_session_instance),
):
    tasks = await CandidateCommunicationService(session).list_tasks(
        current_user=current_user, status=task_status, priority=priority, keyword=keyword
    )
    return {"items": [_task(item) for item in tasks]}


@router.get("/tasks/{task_id}", summary="获取 HR 待办详情")
async def task_detail(
    task_id: str,
    current_user: UserModel = Depends(require_permission(PermissionCode.CANDIDATE_COMMUNICATION_USE)),
    session: AsyncSession = Depends(get_session_instance),
):
    try:
        task = await CandidateCommunicationService(session).get_task(task_id=task_id, current_user=current_user)
    except CandidateCommunicationNotFoundError as exc:
        _raise_not_found(exc)
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload
    from models.candidate_communication import CandidateFollowupTaskNoteModel
    notes = list(await session.scalars(select(CandidateFollowupTaskNoteModel).where(
        CandidateFollowupTaskNoteModel.task_id == task.id
    ).options(selectinload(CandidateFollowupTaskNoteModel.author)).order_by(CandidateFollowupTaskNoteModel.created_at.asc())))
    return {"task": _task(task), "notes": [{
        "id": note.id, "content": note.content, "author_name": getattr(getattr(note, "author", None), "username", None),
        "created_at": note.created_at,
    } for note in notes]}


@router.patch("/tasks/{task_id}", summary="更新 HR 待办状态")
async def update_task(
    task_id: str, data: UpdateFollowupTaskSchema,
    current_user: UserModel = Depends(require_permission(PermissionCode.CANDIDATE_COMMUNICATION_USE)),
    session: AsyncSession = Depends(get_session_instance),
):
    try:
        async with session.begin():
            task = await CandidateCommunicationService(session).update_task_status(
                task_id=task_id, status=data.status, current_user=current_user
            )
    except CandidateCommunicationNotFoundError as exc:
        _raise_not_found(exc)
    return {"task": _task(task)}


@router.post("/tasks/{task_id}/notes", summary="添加 HR 待办跟进备注")
async def add_task_note(
    task_id: str, data: CreateFollowupTaskNoteSchema,
    current_user: UserModel = Depends(require_permission(PermissionCode.CANDIDATE_COMMUNICATION_USE)),
    session: AsyncSession = Depends(get_session_instance),
):
    try:
        async with session.begin():
            note = await CandidateCommunicationService(session).add_task_note(
                task_id=task_id, content=data.content, current_user=current_user
            )
    except CandidateCommunicationNotFoundError as exc:
        _raise_not_found(exc)
    return {"note": {"id": note.id, "content": note.content, "author_name": current_user.username, "created_at": note.created_at}}
