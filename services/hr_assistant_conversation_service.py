"""HR 招聘助手会话应用服务。"""

import json
from typing import Any, AsyncIterator

from loguru import logger

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

    async def list_conversations(
        self,
        *,
        user_id: str,
        page: int,
        size: int,
        status: AssistantConversationStatusEnum | None = None,
        keyword: str | None = None,
    ):
        """分页查看当前用户自己的会话。"""

        async with AsyncSessionFactory() as session:
            async with session.begin():
                return await AssistantConversationRepo(session).list_owned_conversations(
                    user_id=user_id,
                    page=page,
                    size=size,
                    status=status,
                    keyword=keyword,
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

        await self._persist_user_message(
            user_id=user_id,
            conversation_id=conversation_id,
            content=content,
        )

        async with HRAssistantAgent(current_user_id=user_id) as agent:
            response = await agent.ainvoke(
                messages=[{"role": "user", "content": content}],
                thread_id=self.build_thread_id(user_id, conversation_id),
            )

        assistant_message, answer, artifacts, _ = await self._persist_assistant_turn(
            conversation_id=conversation_id,
            response=response,
        )

        return {
            "conversation_id": conversation_id,
            "message_id": assistant_message.id,
            "answer": answer,
            "artifacts": artifacts,
        }

    async def ensure_active_conversation(
        self,
        *,
        user_id: str,
        conversation_id: str,
    ) -> None:
        """在开始 SSE 响应前校验会话，确保能返回正确的 HTTP 状态码。"""

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

    async def stream_message(
        self,
        *,
        user_id: str,
        conversation_id: str,
        content: str,
    ) -> AsyncIterator[dict]:
        """流式执行一轮对话，并输出稳定、脱敏的应用层事件。

        临时 token 只输出给客户端；只有 Graph 成功结束后才写入最终助手
        消息和工具审计摘要，避免断流时产生伪造的成功记录。
        """

        thread_id = self.build_thread_id(user_id, conversation_id)
        started_tool_call_ids: set[str] = set()
        completed_tool_call_ids: set[str] = set()

        try:
            user_message = await self._persist_user_message(
                user_id=user_id,
                conversation_id=conversation_id,
                content=content,
            )
            yield {
                "event": "message_start",
                "data": {
                    "conversation_id": conversation_id,
                    "user_message_id": user_message.id,
                },
            }

            async with HRAssistantAgent(current_user_id=user_id) as agent:
                async for event in agent.astream(
                    messages=[{"role": "user", "content": content}],
                    thread_id=thread_id,
                ):
                    mode, payload = self._split_stream_event(event)
                    if mode == "messages":
                        for item in self._extract_text_stream_events(payload):
                            yield item
                    elif mode == "updates":
                        for item in self._extract_tool_stream_events(
                            payload=payload,
                            started_tool_call_ids=started_tool_call_ids,
                            completed_tool_call_ids=completed_tool_call_ids,
                        ):
                            yield item

                response = await agent.get_state_values(thread_id)

            assistant_message, answer, artifacts, candidate_ids = await self._persist_assistant_turn(
                conversation_id=conversation_id,
                response=response,
            )
            yield {
                "event": "message_end",
                "data": {
                    "message_id": assistant_message.id,
                    "answer": answer,
                    "artifacts": artifacts,
                    "candidate_ids": candidate_ids,
                },
            }
        except Exception as exc:
            # 不将模型/数据库堆栈或用户输入暴露给客户端；详细异常仅记录服务端日志。
            logger.exception(
                "HR助手 SSE 执行失败 conversation_id={} error_type={}",
                conversation_id,
                type(exc).__name__,
            )
            yield {
                "event": "error",
                "data": {
                    "code": "assistant_stream_failed",
                    "message": "招聘助手暂时无法完成本次请求，请稍后重试。",
                },
            }

    async def _persist_user_message(
        self,
        *,
        user_id: str,
        conversation_id: str,
        content: str,
    ):
        """短事务写入用户消息；同步和 SSE 两条链路共用。"""

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
                user_message = await repo.create_message(
                    conversation_id=conversation_id,
                    role=AssistantMessageRoleEnum.USER,
                    content=content,
                )
                await repo.update_conversation(
                    conversation_id=conversation_id,
                    touch_last_message_at=True,
                )
                return user_message

    async def _persist_assistant_turn(
        self,
        *,
        conversation_id: str,
        response: dict,
    ):
        """短事务写入最终回答、产物和工具审计摘要。"""

        messages = response.get("messages", [])
        current_turn_messages = self._get_current_turn_messages(messages)
        answer = self._extract_answer(current_turn_messages)
        artifacts = self._extract_artifacts(current_turn_messages)
        tool_summaries = self._extract_tool_summaries(current_turn_messages)
        candidate_ids = self._collect_candidate_ids(artifacts, tool_summaries)

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

        return assistant_message, answer, artifacts, candidate_ids

    @staticmethod
    def _split_stream_event(event: Any) -> tuple[str | None, Any]:
        """兼容 LangGraph 多 stream_mode 返回的 ``(mode, data)`` 格式。"""

        if isinstance(event, tuple) and len(event) == 2:
            return event[0], event[1]
        return None, event

    @staticmethod
    def _extract_text_stream_events(payload: Any) -> list[dict]:
        """从 LangGraph messages 模式中提取 AI 可见文本增量。"""

        if not isinstance(payload, tuple) or not payload:
            return []
        message = payload[0]
        # LangGraph messages 模式实际输出的是 AIMessageChunk；不能只判断
        # 最终消息的 ``ai`` 类型，否则 token 会被全部丢弃而退化为一次性返回。
        message_type = str(getattr(message, "type", "")).lower()
        if message_type not in {"ai", "assistant", "aimessagechunk"}:
            return []
        # 工具调用阶段的 chunk 可能包含参数片段或模型内部过程，不能输出给客户端。
        if getattr(message, "tool_call_chunks", None) or getattr(message, "tool_calls", None):
            return []
        content = getattr(message, "content", "")
        if not isinstance(content, str) or not content:
            return []
        return [{"event": "content_delta", "data": {"content": content}}]

    @classmethod
    def _extract_tool_stream_events(
        cls,
        *,
        payload: Any,
        started_tool_call_ids: set[str],
        completed_tool_call_ids: set[str],
    ) -> list[dict]:
        """把 Graph 节点更新转换为工具开始/结束事件。"""

        if not isinstance(payload, dict):
            return []

        events: list[dict] = []
        for update in payload.values():
            if not isinstance(update, dict):
                continue
            for message in update.get("messages", []):
                message_type = getattr(message, "type", None)
                if message_type in {"ai", "assistant"}:
                    for tool_call in getattr(message, "tool_calls", []) or []:
                        tool_name = tool_call.get("name", "unknown_tool")
                        call_id = tool_call.get("id") or cls._tool_start_fallback_key(tool_call)
                        if call_id in started_tool_call_ids:
                            continue
                        started_tool_call_ids.add(call_id)
                        events.append(
                            {
                                "event": "tool_start",
                                "data": {
                                    "tool": tool_name,
                                    "display": cls._tool_display_name(tool_name, started=True),
                                },
                            }
                        )
                elif message_type == "tool":
                    tool_name = getattr(message, "name", None) or "unknown_tool"
                    call_id = getattr(message, "tool_call_id", None) or cls._tool_end_fallback_key(message)
                    if call_id in completed_tool_call_ids:
                        continue
                    completed_tool_call_ids.add(call_id)
                    events.append(
                        {
                            "event": "tool_end",
                            "data": {
                                "tool": tool_name,
                                "display": cls._tool_display_name(tool_name, started=False),
                            },
                        }
                    )
        return events

    @staticmethod
    def _tool_start_fallback_key(tool_call: dict) -> str:
        """为缺失 tool_call_id 的模型更新生成可重复计算的去重键。"""

        tool_name = tool_call.get("name", "unknown_tool")
        arguments = tool_call.get("args", tool_call.get("arguments", {}))
        serialized_arguments = json.dumps(
            arguments,
            ensure_ascii=False,
            sort_keys=True,
            default=str,
        )
        return f"{tool_name}:start:{serialized_arguments}"

    @staticmethod
    def _tool_end_fallback_key(message: Any) -> str:
        """为缺失 tool_call_id 的工具更新生成稳定的去重键。"""

        tool_name = getattr(message, "name", None) or "unknown_tool"
        content = getattr(message, "content", "")
        return f"{tool_name}:end:{content if isinstance(content, str) else str(content)}"

    @staticmethod
    def _tool_display_name(tool_name: str, *, started: bool) -> str:
        """返回不含候选人数据的前端过程提示。"""

        action = "正在" if started else "已完成"
        tool_display_map = {
            "search_talent_pool": "检索人才库",
            "search_recruiting_knowledge": "检索企业制度",
            "get_candidate_detail": "获取候选人详情",
            "compare_candidates": "对比候选人",
        }
        return f"{action}{tool_display_map.get(tool_name, '调用工具')}"

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
        knowledge_artifact: dict | None = None
        knowledge_sources_by_id: dict[str, dict] = {}
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
            elif artifact_type == "knowledge_sources":
                if knowledge_artifact is None:
                    knowledge_artifact = {
                        "type": "knowledge_sources",
                        "title": "制度知识来源",
                        "sources": [],
                        "raw": {**payload, "sources": []},
                    }
                    artifacts.append(knowledge_artifact)
                for source in payload.get("sources", []):
                    if not isinstance(source, dict):
                        continue
                    source_id = source.get("source_id")
                    if not source_id:
                        continue
                    existing_source = knowledge_sources_by_id.get(source_id)
                    if existing_source is None:
                        copied_source = dict(source)
                        knowledge_sources_by_id[source_id] = copied_source
                        knowledge_artifact["sources"].append(copied_source)
                        knowledge_artifact["raw"]["sources"].append(copied_source)
                        continue
                    # 同一来源经不同检索路径再次命中时，保留首次排序位置，
                    # 但用后续返回的非空字段（尤其正文）补全它。
                    for field, value in source.items():
                        if not existing_source.get(field) and value:
                            existing_source[field] = value
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
            source_ids = [
                source.get("source_id")
                for source in payload.get("sources", [])
                if isinstance(source, dict) and source.get("source_id")
            ]
            result_count = len(source_ids) if payload.get("artifact_type") == "knowledge_sources" else len(candidate_ids)
            result_label = "制度来源" if payload.get("artifact_type") == "knowledge_sources" else "候选人"
            metadata = {
                "artifact_type": payload.get("artifact_type"),
                "candidate_ids": candidate_ids,
            }
            if source_ids:
                metadata["source_ids"] = source_ids
            summaries.append(
                {
                    "tool_name": tool_name,
                    "content": f"工具 {tool_name} 已执行，命中 {result_count} 个{result_label}",
                    "metadata": metadata,
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
