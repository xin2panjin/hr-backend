"""HR 招聘助手会话应用服务。"""

import json
from typing import Any

from agents.hr_assistant.agent import HRAssistantAgent
from models import AsyncSessionFactory
from models.assistant_conversation import (
    AssistantConversationStatusEnum,
    AssistantMessageRoleEnum,
)
from repository.assistant_conversation_repo import AssistantConversationRepo


class AssistantConversationNotFoundError(ValueError):
    """会话不存在或不属于当前用户。"""


class AssistantConversationInactiveError(ValueError):
    """归档或删除的会话不能继续发起消息。"""


class HRAssistantConversationService:
    """管理会话业务数据，并复用现有 HR Agent 的对话能力。"""

    @staticmethod
    def build_thread_id(user_id: str, conversation_id: str) -> str:
        """构造用户隔离的稳定 LangGraph thread_id。"""

        return f"hr-assistant:{user_id}:{conversation_id}"

    async def create_conversation(self, *, user_id: str, title: str = "新对话"):
        """创建一条活跃会话。"""

        async with AsyncSessionFactory() as session:
            async with session.begin():
                return await AssistantConversationRepo(session).create_conversation(
                    user_id=user_id,
                    title=title,
                )

    async def list_conversations(self, *, user_id: str, page: int, size: int):
        """分页查看当前用户自己的会话。"""

        async with AsyncSessionFactory() as session:
            async with session.begin():
                return await AssistantConversationRepo(session).list_owned_conversations(
                    user_id=user_id,
                    page=page,
                    size=size,
                )

    async def list_messages(self, *, user_id: str, conversation_id: str):
        """查看会话历史；工具审计记录不会直接返回给前端。"""

        async with AsyncSessionFactory() as session:
            async with session.begin():
                repo = AssistantConversationRepo(session)
                await self._get_owned_conversation_or_raise(
                    repo=repo,
                    conversation_id=conversation_id,
                    user_id=user_id,
                )
                return await repo.list_messages(conversation_id=conversation_id)

    async def update_conversation(
        self,
        *,
        user_id: str,
        conversation_id: str,
        title: str | None = None,
        status: AssistantConversationStatusEnum | None = None,
    ):
        """重命名、归档或恢复当前用户的会话。"""

        async with AsyncSessionFactory() as session:
            async with session.begin():
                repo = AssistantConversationRepo(session)
                conversation = await self._get_owned_conversation_or_raise(
                    repo=repo,
                    conversation_id=conversation_id,
                    user_id=user_id,
                )
                if conversation.status == AssistantConversationStatusEnum.DELETED:
                    raise AssistantConversationNotFoundError("会话不存在")
                await repo.update_conversation(
                    conversation_id=conversation_id,
                    title=title,
                    status=status,
                )
                # 更新 ORM 对象，避免调用方拿到修改前的内容。
                if title is not None:
                    conversation.title = title
                if status is not None:
                    conversation.status = status
                return conversation

    async def delete_conversation(self, *, user_id: str, conversation_id: str) -> None:
        """软删除会话，保留消息以满足审计和恢复需求。"""

        await self.update_conversation(
            user_id=user_id,
            conversation_id=conversation_id,
            status=AssistantConversationStatusEnum.DELETED,
        )

    async def send_message(
        self,
        *,
        user_id: str,
        conversation_id: str,
        content: str,
    ) -> dict:
        """持久化一轮对话，并返回当前轮的最终回答和前端产物。"""

        # 第一段短事务：先确认所有权并保存用户消息。模型调用不持有事务。
        async with AsyncSessionFactory() as session:
            async with session.begin():
                repo = AssistantConversationRepo(session)
                conversation = await self._get_owned_conversation_or_raise(
                    repo=repo,
                    conversation_id=conversation_id,
                    user_id=user_id,
                )
                if conversation.status != AssistantConversationStatusEnum.ACTIVE:
                    raise AssistantConversationInactiveError("当前会话已归档或删除")
                await repo.create_message(
                    conversation_id=conversation_id,
                    role=AssistantMessageRoleEnum.USER,
                    content=content,
                )
                await repo.update_conversation(
                    conversation_id=conversation_id,
                    touch_last_message_at=True,
                )

        async with HRAssistantAgent(current_user_id=user_id) as agent:
            response = await agent.ainvoke(
                messages=[{"role": "user", "content": content}],
                thread_id=self.build_thread_id(user_id, conversation_id),
            )

        messages = response.get("messages", [])
        current_turn_messages = self._get_current_turn_messages(messages)
        answer = self._extract_answer(current_turn_messages)
        artifacts = self._extract_artifacts(current_turn_messages)
        tool_summaries = self._extract_tool_summaries(current_turn_messages)
        candidate_ids = self._collect_candidate_ids(artifacts, tool_summaries)

        # 第二段短事务：落库最终回答和经过脱敏处理的工具审计摘要。
        async with AsyncSessionFactory() as session:
            async with session.begin():
                repo = AssistantConversationRepo(session)
                assistant_message = await repo.create_message(
                    conversation_id=conversation_id,
                    role=AssistantMessageRoleEnum.ASSISTANT,
                    content=answer,
                    metadata={
                        "candidate_ids": candidate_ids,
                        "artifacts": artifacts,
                        "tool_names": [item["tool_name"] for item in tool_summaries],
                    },
                )
                for item in tool_summaries:
                    await repo.create_message(
                        conversation_id=conversation_id,
                        role=AssistantMessageRoleEnum.TOOL,
                        content=item["content"],
                        tool_name=item["tool_name"],
                        metadata=item["metadata"],
                    )
                await repo.update_conversation(
                    conversation_id=conversation_id,
                    touch_last_message_at=True,
                )

        return {
            "conversation_id": conversation_id,
            "message_id": assistant_message.id,
            "answer": answer,
            "artifacts": artifacts,
        }

    @staticmethod
    async def _get_owned_conversation_or_raise(*, repo, conversation_id: str, user_id: str):
        conversation = await repo.get_owned_conversation(
            conversation_id=conversation_id,
            user_id=user_id,
        )
        if not conversation or conversation.status == AssistantConversationStatusEnum.DELETED:
            raise AssistantConversationNotFoundError("会话不存在")
        return conversation

    @staticmethod
    def _get_current_turn_messages(messages: list[Any]) -> list[Any]:
        """从累计 checkpoint 消息中截取当前轮产生的内容。"""

        last_user_index = -1
        for index, message in enumerate(messages):
            if getattr(message, "type", None) in {"human", "user"}:
                last_user_index = index
        return messages[last_user_index + 1 :] if last_user_index >= 0 else messages

    @staticmethod
    def _extract_answer(messages: list[Any]) -> str:
        """取当前轮最后一条 AI 文本，避免误把工具消息当成最终回答。"""

        for message in reversed(messages):
            if getattr(message, "type", None) in {"ai", "assistant"}:
                content = getattr(message, "content", "")
                return content if isinstance(content, str) else str(content)
        return ""

    @classmethod
    def _extract_artifacts(cls, messages: list[Any]) -> list[dict]:
        """从工具结果提取前端卡片，不保存模型内部消息。"""

        artifacts: list[dict] = []
        for message in messages:
            if getattr(message, "type", None) != "tool":
                continue
            payload = cls._parse_tool_payload(getattr(message, "content", None))
            if not payload:
                continue
            artifact_type = payload.get("artifact_type")
            if artifact_type == "candidate_cards":
                artifacts.append(
                    {
                        "type": "candidate_cards",
                        "title": "候选人搜索结果",
                        "candidates": [
                            cls._build_candidate_card(item)
                            for item in payload.get("candidates", [])
                            if item.get("candidate_id")
                        ],
                        # 沿用已有前端协议：详情、对比卡需要读取脱敏工具结果。
                        "raw": payload,
                    }
                )
            elif artifact_type == "candidate_detail" and payload.get("candidate_id"):
                artifacts.append(
                    {
                        "type": "candidate_detail",
                        "title": "候选人详情",
                        "candidates": [cls._build_candidate_card(payload)],
                        "raw": payload,
                    }
                )
            elif artifact_type == "candidate_comparison":
                artifacts.append(
                    {
                        "type": "candidate_comparison",
                        "title": "候选人对比结果",
                        "candidates": [
                            cls._build_candidate_card(item)
                            for item in payload.get("candidates", [])
                            if item.get("candidate_id")
                        ],
                        "raw": payload,
                    }
                )
        return artifacts

    @staticmethod
    def _build_candidate_card(candidate: dict) -> dict:
        """生成前端卡片最小字段，避免把候选人详情原文写进消息元数据。"""

        position = candidate.get("position") or {}
        status = candidate.get("status")
        return {
            "candidate_id": candidate.get("candidate_id"),
            "name": candidate.get("name"),
            "position_title": candidate.get("position_title") or position.get("title"),
            "status": getattr(status, "value", status),
            "score": candidate.get("score"),
            "summary": candidate.get("profile_text") or (candidate.get("ai_score") or {}).get("summary"),
            "actions": [
                {
                    "type": "open_candidate_detail",
                    "label": "查看详情",
                    "candidate_id": candidate.get("candidate_id"),
                }
            ],
        }

    @classmethod
    def _extract_tool_summaries(cls, messages: list[Any]) -> list[dict]:
        """为审计生成脱敏工具摘要，不原样保存工具 JSON。"""

        summaries: list[dict] = []
        for message in messages:
            if getattr(message, "type", None) != "tool":
                continue
            payload = cls._parse_tool_payload(getattr(message, "content", None)) or {}
            candidate_ids = cls._candidate_ids_from_payload(payload)
            tool_name = getattr(message, "name", None) or "unknown_tool"
            summaries.append(
                {
                    "tool_name": tool_name,
                    "content": f"工具 {tool_name} 已执行，命中 {len(candidate_ids)} 位候选人",
                    "metadata": {
                        "artifact_type": payload.get("artifact_type"),
                        "candidate_ids": candidate_ids,
                    },
                }
            )
        return summaries

    @staticmethod
    def _parse_tool_payload(content: Any) -> dict | None:
        if not isinstance(content, str):
            return None
        try:
            payload = json.loads(content)
        except json.JSONDecodeError:
            return None
        return payload if isinstance(payload, dict) else None

    @staticmethod
    def _candidate_ids_from_payload(payload: dict) -> list[str]:
        candidate_ids = []
        if payload.get("candidate_id"):
            candidate_ids.append(payload["candidate_id"])
        for candidate in payload.get("candidates", []):
            if candidate_id := candidate.get("candidate_id"):
                candidate_ids.append(candidate_id)
        return list(dict.fromkeys(candidate_ids))

    @classmethod
    def _collect_candidate_ids(
        cls,
        artifacts: list[dict],
        tool_summaries: list[dict],
    ) -> list[str]:
        candidate_ids = []
        for artifact in artifacts:
            candidate_ids.extend(
                candidate["candidate_id"]
                for candidate in artifact.get("candidates", [])
                if candidate.get("candidate_id")
            )
        for summary in tool_summaries:
            candidate_ids.extend(summary["metadata"].get("candidate_ids", []))
        return list(dict.fromkeys(candidate_ids))
