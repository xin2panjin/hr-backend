"""候选人会话、HR 待办及 AI 洞察的应用服务。"""

from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from agents.llms import deepseek_llm, qwen_llm
from iam.policies.candidate_policy import CandidatePolicy
from models import AsyncSessionFactory
from models.candidate import CandidateModel
from models.candidate_communication import (
    CandidateConversationInsightModel, CandidateConversationMessageModel,
    CandidateConversationModel, CandidateConversationReadStateModel,
    CandidateFollowupTaskModel, CandidateFollowupTaskNoteModel,
    CandidateFollowupTaskStatusEnum, CandidateInsightOutboxModel,
    CandidateInsightOutboxStatusEnum, CandidateMessageSenderEnum,
)
from models.positions import PositionModel
from schemas.candidate_communication_schema import CandidateInsightExtractionSchema


class CandidateCommunicationNotFoundError(Exception):
    pass


class CandidateCommunicationService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def list_portal_applications(self, email: str) -> list[CandidateModel]:
        result = await self.session.scalars(
            select(CandidateModel)
            .where(func.lower(CandidateModel.email) == email.lower())
            .options(selectinload(CandidateModel.position))
            .order_by(CandidateModel.created_at.desc())
        )
        return list(result)

    async def get_portal_candidate(self, *, candidate_id: str, email: str) -> CandidateModel:
        candidate = await self.session.scalar(
            select(CandidateModel)
            .where(CandidateModel.id == candidate_id, func.lower(CandidateModel.email) == email.lower())
            .options(selectinload(CandidateModel.position).selectinload(PositionModel.creator))
        )
        if not candidate:
            raise CandidateCommunicationNotFoundError()
        return candidate

    async def get_or_create_conversation(self, candidate: CandidateModel) -> CandidateConversationModel:
        conversation = await self.session.scalar(
            select(CandidateConversationModel).where(CandidateConversationModel.candidate_id == candidate.id)
        )
        if conversation:
            return conversation
        conversation = CandidateConversationModel(candidate_id=candidate.id, owner_id=candidate.position.creator_id)
        self.session.add(conversation)
        await self.session.flush([conversation])
        return conversation

    async def list_messages_for_portal(self, *, candidate_id: str, email: str) -> tuple[CandidateModel, list[CandidateConversationMessageModel], CandidateConversationModel | None]:
        candidate = await self.get_portal_candidate(candidate_id=candidate_id, email=email)
        conversation = await self.session.scalar(
            select(CandidateConversationModel).where(CandidateConversationModel.candidate_id == candidate.id)
        )
        if not conversation:
            return candidate, [], None
        messages = list(await self.session.scalars(
            select(CandidateConversationMessageModel)
            .where(CandidateConversationMessageModel.conversation_id == conversation.id)
            .order_by(CandidateConversationMessageModel.created_at.asc())
        ))
        return candidate, messages, conversation

    async def send_portal_message(self, *, candidate_id: str, email: str, content: str) -> CandidateConversationMessageModel:
        candidate = await self.get_portal_candidate(candidate_id=candidate_id, email=email)
        conversation = await self.get_or_create_conversation(candidate)
        # 锁住会话，保证并发短消息只保留最后一条对应的 outbox 事件。
        await self.session.execute(select(CandidateConversationModel).where(
            CandidateConversationModel.id == conversation.id
        ).with_for_update())
        previous_events = list(await self.session.scalars(
            select(CandidateInsightOutboxModel)
            .join(CandidateConversationMessageModel, CandidateInsightOutboxModel.source_message_id == CandidateConversationMessageModel.id)
            .where(CandidateConversationMessageModel.conversation_id == conversation.id)
            .where(CandidateInsightOutboxModel.status.in_([
                CandidateInsightOutboxStatusEnum.PENDING,
                CandidateInsightOutboxStatusEnum.FAILED,
            ]))
        ))
        for event in previous_events:
            event.status = CandidateInsightOutboxStatusEnum.COMPLETED
            event.processed_at = datetime.now()
            event.last_error = "已被同一会话的后续候选人消息合并"
        message = CandidateConversationMessageModel(
            conversation_id=conversation.id, sender_type=CandidateMessageSenderEnum.CANDIDATE, content=content.strip()
        )
        self.session.add(message)
        conversation.last_message_at = datetime.now()
        await self.session.flush([message])
        self.session.add(CandidateInsightOutboxModel(
            source_message_id=message.id,
            available_at=datetime.now() + CandidateCommunicationInsightWorker.quiet_period,
        ))
        return message

    async def _get_hr_conversation(self, *, candidate_id: str, current_user) -> CandidateConversationModel:
        conversation = await self.session.scalar(
            select(CandidateConversationModel)
            .join(CandidateModel, CandidateConversationModel.candidate_id == CandidateModel.id)
            .where(CandidateConversationModel.candidate_id == candidate_id)
            .options(
                selectinload(CandidateConversationModel.candidate).selectinload(CandidateModel.position).selectinload(PositionModel.creator),
                selectinload(CandidateConversationModel.candidate).selectinload(CandidateModel.ai_score),
            )
        )
        if not conversation or not CandidatePolicy.can_read(current_user, conversation.candidate):
            raise CandidateCommunicationNotFoundError()
        return conversation

    async def list_hr_conversations(self, *, current_user, keyword: str | None = None) -> list[tuple[CandidateConversationModel, int]]:
        stmt = (
            select(CandidateConversationModel)
            .join(CandidateModel, CandidateConversationModel.candidate_id == CandidateModel.id)
            .options(selectinload(CandidateConversationModel.candidate).selectinload(CandidateModel.position).selectinload(PositionModel.creator))
            .order_by(CandidateConversationModel.last_message_at.desc())
        )
        stmt = CandidatePolicy.apply_sql_scope(stmt, CandidatePolicy.resolve_scope(current_user))
        if keyword and keyword.strip():
            pattern = f"%{keyword.strip()}%"
            stmt = stmt.where((CandidateModel.name.ilike(pattern)) | (CandidateModel.email.ilike(pattern)) | (PositionModel.title.ilike(pattern)))
        conversations = list(await self.session.scalars(stmt))
        output: list[tuple[CandidateConversationModel, int]] = []
        for conversation in conversations:
            unread_count = 0
            if conversation.owner_id == current_user.id:
                read_at = await self.session.scalar(select(CandidateConversationReadStateModel.last_read_at).where(
                    CandidateConversationReadStateModel.conversation_id == conversation.id,
                    CandidateConversationReadStateModel.user_id == current_user.id,
                ))
                count_stmt = select(func.count(CandidateConversationMessageModel.id)).where(
                    CandidateConversationMessageModel.conversation_id == conversation.id,
                    CandidateConversationMessageModel.sender_type == CandidateMessageSenderEnum.CANDIDATE,
                )
                if read_at:
                    count_stmt = count_stmt.where(CandidateConversationMessageModel.created_at > read_at)
                unread_count = int(await self.session.scalar(count_stmt) or 0)
            output.append((conversation, unread_count))
        return output

    async def hr_conversation_detail(self, *, candidate_id: str, current_user) -> tuple[CandidateConversationModel, list[CandidateConversationMessageModel], CandidateConversationInsightModel | None, str | None]:
        conversation = await self._get_hr_conversation(candidate_id=candidate_id, current_user=current_user)
        messages = list(await self.session.scalars(select(CandidateConversationMessageModel).where(
            CandidateConversationMessageModel.conversation_id == conversation.id
        ).order_by(CandidateConversationMessageModel.created_at.asc())))
        insight = await self.session.scalar(select(CandidateConversationInsightModel).where(
            CandidateConversationInsightModel.conversation_id == conversation.id
        ).order_by(CandidateConversationInsightModel.created_at.desc()))
        analysis_status = await self.session.scalar(
            select(CandidateInsightOutboxModel.status)
            .join(CandidateConversationMessageModel, CandidateInsightOutboxModel.source_message_id == CandidateConversationMessageModel.id)
            .where(CandidateConversationMessageModel.conversation_id == conversation.id)
            .order_by(CandidateConversationMessageModel.created_at.desc())
            .limit(1)
        )
        return conversation, messages, insight, getattr(analysis_status, "value", analysis_status)

    async def send_hr_message(self, *, candidate_id: str, current_user, content: str) -> CandidateConversationMessageModel:
        conversation = await self._get_hr_conversation(candidate_id=candidate_id, current_user=current_user)
        message = CandidateConversationMessageModel(
            conversation_id=conversation.id, sender_type=CandidateMessageSenderEnum.HR,
            sender_user_id=current_user.id, content=content.strip(),
        )
        self.session.add(message)
        conversation.last_message_at = datetime.now()
        return message

    async def mark_read(self, *, candidate_id: str, current_user) -> None:
        conversation = await self._get_hr_conversation(candidate_id=candidate_id, current_user=current_user)
        if conversation.owner_id != current_user.id:
            return
        read_state = await self.session.scalar(select(CandidateConversationReadStateModel).where(
            CandidateConversationReadStateModel.conversation_id == conversation.id,
            CandidateConversationReadStateModel.user_id == current_user.id,
        ))
        if read_state:
            read_state.last_read_at = datetime.now()
        else:
            self.session.add(CandidateConversationReadStateModel(conversation_id=conversation.id, user_id=current_user.id))

    async def list_tasks(self, *, current_user, status: CandidateFollowupTaskStatusEnum | None = None, priority: str | None = None, keyword: str | None = None) -> list[CandidateFollowupTaskModel]:
        stmt = select(CandidateFollowupTaskModel).join(CandidateModel, CandidateFollowupTaskModel.candidate_id == CandidateModel.id).options(
            selectinload(CandidateFollowupTaskModel.candidate).selectinload(CandidateModel.position),
            selectinload(CandidateFollowupTaskModel.assignee),
        ).order_by(CandidateFollowupTaskModel.created_at.desc())
        # Task 模型不反向维护 candidate relationship；范围约束必须在 SQL 层完成。
        stmt = CandidatePolicy.apply_sql_scope(stmt, CandidatePolicy.resolve_scope(current_user))
        if status:
            stmt = stmt.where(CandidateFollowupTaskModel.status == status)
        if priority:
            stmt = stmt.where(CandidateFollowupTaskModel.priority == priority)
        if keyword and keyword.strip():
            stmt = stmt.where(CandidateFollowupTaskModel.title.ilike(f"%{keyword.strip()}%"))
        return list(await self.session.scalars(stmt))

    async def get_task(self, *, task_id: str, current_user) -> CandidateFollowupTaskModel:
        task = await self.session.scalar(select(CandidateFollowupTaskModel).where(CandidateFollowupTaskModel.id == task_id).options(
            selectinload(CandidateFollowupTaskModel.assignee),
        ))
        if not task:
            raise CandidateCommunicationNotFoundError()
        candidate = await self.session.scalar(select(CandidateModel).where(CandidateModel.id == task.candidate_id).options(
            selectinload(CandidateModel.position).selectinload(PositionModel.creator)
        ))
        if not candidate or not CandidatePolicy.can_read(current_user, candidate):
            raise CandidateCommunicationNotFoundError()
        task._candidate = candidate
        return task

    async def update_task_status(self, *, task_id: str, status: CandidateFollowupTaskStatusEnum, current_user) -> CandidateFollowupTaskModel:
        task = await self.get_task(task_id=task_id, current_user=current_user)
        task.status = status
        return task

    async def add_task_note(self, *, task_id: str, content: str, current_user) -> CandidateFollowupTaskNoteModel:
        await self.get_task(task_id=task_id, current_user=current_user)
        note = CandidateFollowupTaskNoteModel(task_id=task_id, author_id=current_user.id, content=content.strip())
        self.session.add(note)
        return note


class CandidateCommunicationInsightWorker:
    """短事务领取 outbox，模型调用和落库分离，避免长时间持锁。"""

    max_attempts = 3
    quiet_period = timedelta(minutes=5)

    async def process_pending(self, limit: int = 10) -> int:
        async with AsyncSessionFactory() as session:
            async with session.begin():
                events = list(await session.scalars(
                    select(CandidateInsightOutboxModel)
                    .where(CandidateInsightOutboxModel.status.in_([CandidateInsightOutboxStatusEnum.PENDING, CandidateInsightOutboxStatusEnum.FAILED]))
                    .where(CandidateInsightOutboxModel.attempts < self.max_attempts)
                    .where(CandidateInsightOutboxModel.available_at <= datetime.now())
                    .order_by(CandidateInsightOutboxModel.created_at.asc())
                    .with_for_update(skip_locked=True)
                    .limit(limit)
                ))
                event_ids = [event.id for event in events]
                for event in events:
                    event.status = CandidateInsightOutboxStatusEnum.PROCESSING
                    event.attempts += 1
        completed = 0
        for event_id in event_ids:
            if await self._process_one(event_id):
                completed += 1
        return completed

    async def _process_one(self, event_id: str) -> bool:
        async with AsyncSessionFactory() as session:
            event = await session.get(CandidateInsightOutboxModel, event_id)
            if not event:
                return False
            message = await session.get(CandidateConversationMessageModel, event.source_message_id)
            if not message:
                return await self._fail(session, event, "源消息不存在")
            conversation = await session.get(CandidateConversationModel, message.conversation_id)
            candidate = await session.get(CandidateModel, conversation.candidate_id) if conversation else None
            if not conversation or not candidate:
                return await self._fail(session, event, "会话或候选人不存在")
            messages = list(await session.scalars(select(CandidateConversationMessageModel).where(
                CandidateConversationMessageModel.conversation_id == conversation.id
            ).order_by(CandidateConversationMessageModel.created_at.desc()).limit(20)))
            messages.reverse()
            try:
                extraction = await self._extract(candidate=candidate, messages=messages)
            except Exception as exc:
                return await self._fail(session, event, str(exc)[:1000])
            if event.status != CandidateInsightOutboxStatusEnum.PROCESSING:
                return False
            evidence = [{"message_id": message.id, "content": message.content}]
            session.add(CandidateConversationInsightModel(
                conversation_id=conversation.id, source_message_id=message.id, summary=extraction.summary or message.content,
                stage=extraction.stage, intent=extraction.intent, confirmed_facts=extraction.confirmed_facts,
                candidate_requests=extraction.candidate_requests, hr_commitments=extraction.hr_commitments,
                risks=extraction.risks, next_step=extraction.next_step, evidence=evidence,
            ))
            if extraction.task_title:
                session.add(CandidateFollowupTaskModel(
                    conversation_id=conversation.id, candidate_id=candidate.id, assignee_id=conversation.owner_id,
                    source_outbox_id=event.id, title=extraction.task_title, task_type=extraction.task_type,
                    priority=extraction.task_priority, due_at=extraction.task_due_at, evidence=evidence,
                ))
            event.status = CandidateInsightOutboxStatusEnum.COMPLETED
            event.processed_at = datetime.now()
            event.last_error = None
            await session.commit()
            return True

    async def _fail(self, session: AsyncSession, event: CandidateInsightOutboxModel, error: str) -> bool:
        event.status = CandidateInsightOutboxStatusEnum.FAILED
        event.last_error = error
        await session.commit()
        return False

    async def _extract(self, *, candidate: CandidateModel, messages: list[CandidateConversationMessageModel]) -> CandidateInsightExtractionSchema:
        history = "\n".join(f"{'候选人' if item.sender_type == CandidateMessageSenderEnum.CANDIDATE else 'HR'}：{item.content}" for item in messages)
        prompt = f"""你是招聘沟通分析助手。只提取内部洞察，绝不生成对候选人的回复。
候选人：{candidate.name}；应聘职位：{candidate.position_id}。
会话：\n{history}\n
输出结构化摘要。仅当 HR 需要实际跟进时填 task_title；没有待办则为 null。"""
        for model in (deepseek_llm, qwen_llm):
            try:
                result = await model.with_structured_output(CandidateInsightExtractionSchema).ainvoke(prompt)
                return CandidateInsightExtractionSchema.model_validate(result)
            except Exception:
                continue
        raise RuntimeError("洞察模型调用失败")
