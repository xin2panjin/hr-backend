"""HR 招聘助手会话的数据访问层。"""

from datetime import datetime

from sqlalchemy import func, select, update

from models.assistant_conversation import (
    AssistantConversationModel,
    AssistantConversationStatusEnum,
    AssistantMessageModel,
    AssistantMessageRoleEnum,
)

from . import BaseRepo


class AssistantConversationRepo(BaseRepo):
    """只负责会话和消息的数据库读写，不处理 Agent 调用。"""

    async def create_conversation(
        self,
        *,
        user_id: str,
        title: str,
    ) -> AssistantConversationModel:
        conversation = AssistantConversationModel(user_id=user_id, title=title)
        self.session.add(conversation)
        await self.session.flush([conversation])
        return conversation

    async def get_owned_conversation(
        self,
        *,
        conversation_id: str,
        user_id: str,
    ) -> AssistantConversationModel | None:
        """按会话 ID 和所有者同时查询，避免越权信息泄露。"""

        return await self.session.scalar(
            select(AssistantConversationModel).where(
                AssistantConversationModel.id == conversation_id,
                AssistantConversationModel.user_id == user_id,
            )
        )

    async def list_owned_conversations(
        self,
        *,
        user_id: str,
        page: int,
        size: int,
        status: AssistantConversationStatusEnum | None = None,
        keyword: str | None = None,
    ) -> tuple[list[AssistantConversationModel], int]:
        """分页返回当前用户未删除的会话。"""

        filters = [
            AssistantConversationModel.user_id == user_id,
            AssistantConversationModel.status != AssistantConversationStatusEnum.DELETED,
        ]
        if status is not None:
            filters.append(AssistantConversationModel.status == status)
        if keyword and keyword.strip():
            filters.append(AssistantConversationModel.title.ilike(f"%{keyword.strip()}%"))
        total = await self.session.scalar(
            select(func.count(AssistantConversationModel.id)).where(*filters)
        )
        stmt = (
            select(AssistantConversationModel)
            .where(*filters)
            .order_by(AssistantConversationModel.last_message_at.desc())
            .offset((page - 1) * size)
            .limit(size)
        )
        return list(await self.session.scalars(stmt)), total or 0

    async def list_messages(
        self,
        *,
        conversation_id: str,
        include_tools: bool = False,
    ) -> list[AssistantMessageModel]:
        """按时间顺序读取消息；默认不向前端暴露工具审计记录。"""

        stmt = select(AssistantMessageModel).where(
            AssistantMessageModel.conversation_id == conversation_id
        )
        if not include_tools:
            stmt = stmt.where(AssistantMessageModel.role != AssistantMessageRoleEnum.TOOL)
        stmt = stmt.order_by(AssistantMessageModel.created_at.asc())
        return list(await self.session.scalars(stmt))

    async def create_message(
        self,
        *,
        conversation_id: str,
        role: AssistantMessageRoleEnum,
        content: str,
        tool_name: str | None = None,
        metadata: dict | None = None,
    ) -> AssistantMessageModel:
        message = AssistantMessageModel(
            conversation_id=conversation_id,
            role=role,
            content=content,
            tool_name=tool_name,
            message_metadata=metadata,
        )
        self.session.add(message)
        await self.session.flush([message])
        return message

    async def update_conversation(
        self,
        *,
        conversation_id: str,
        title: str | None = None,
        status: AssistantConversationStatusEnum | None = None,
        touch_last_message_at: bool = False,
    ) -> None:
        values: dict = {}
        if title is not None:
            values["title"] = title
        if status is not None:
            values["status"] = status
        if touch_last_message_at:
            values["last_message_at"] = datetime.now()
        if values:
            await self.session.execute(
                update(AssistantConversationModel)
                .where(AssistantConversationModel.id == conversation_id)
                .values(**values)
            )
