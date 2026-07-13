"""HR 招聘助手会话服务的核心流程测试。"""

import json
from types import SimpleNamespace

import pytest

from models.assistant_conversation import AssistantConversationStatusEnum
from services import hr_assistant_conversation_service as conversation_module
from services.hr_assistant_conversation_service import (
    AssistantConversationInactiveError,
    AssistantConversationNotFoundError,
    HRAssistantConversationService,
)


class FakeTransaction:
    async def __aenter__(self):
        return None

    async def __aexit__(self, exc_type, exc, tb):
        return None


class FakeSession:
    def begin(self):
        return FakeTransaction()


class FakeSessionFactory:
    async def __aenter__(self):
        return FakeSession()

    async def __aexit__(self, exc_type, exc, tb):
        return None


class FakeConversationRepo:
    conversation = SimpleNamespace(
        id="conversation-1",
        user_id="hr-1",
        title="新对话",
        status=AssistantConversationStatusEnum.ACTIVE,
    )
    created_messages = []

    def __init__(self, session):
        self.session = session

    async def get_owned_conversation(self, *, conversation_id, user_id):
        if conversation_id == self.conversation.id and user_id == self.conversation.user_id:
            return self.conversation
        return None

    async def create_message(self, **kwargs):
        self.created_messages.append(kwargs)
        return SimpleNamespace(id=f"message-{len(self.created_messages)}", **kwargs)

    async def update_conversation(self, **kwargs):
        return None


class FakeHRAssistantAgent:
    received_thread_id = None

    def __init__(self, current_user_id):
        self.current_user_id = current_user_id

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def ainvoke(self, *, messages, thread_id):
        type(self).received_thread_id = thread_id
        return {
            "messages": [
                SimpleNamespace(type="human", content=messages[0]["content"]),
                SimpleNamespace(
                    type="tool",
                    name="search_talent_pool",
                    content=json.dumps(
                        {
                            "artifact_type": "candidate_cards",
                            "candidates": [
                                {
                                    "candidate_id": "candidate-1",
                                    "name": "张三",
                                    "position_title": "AI工程师",
                                    "profile_text": "熟悉 Python 和 Milvus",
                                }
                            ],
                        },
                        ensure_ascii=False,
                    ),
                ),
                SimpleNamespace(type="ai", content="找到一位候选人。"),
            ]
        }

    async def astream(self, *, messages, thread_id):
        """模拟 LangGraph 的 messages/updates 双流模式。"""

        type(self).received_thread_id = thread_id
        yield (
            "updates",
            {
                "model": {
                    "messages": [
                        SimpleNamespace(
                            type="ai",
                            tool_calls=[{"id": "call-1", "name": "search_talent_pool"}],
                        )
                    ]
                }
            },
        )
        yield (
            "messages",
            (SimpleNamespace(type="AIMessageChunk", content="找到", tool_call_chunks=[]), {}),
        )
        yield (
            "updates",
            {
                "tools": {
                    "messages": [
                        SimpleNamespace(
                            type="tool",
                            name="search_talent_pool",
                            tool_call_id="call-1",
                        )
                    ]
                }
            },
        )
        yield (
            "messages",
            (SimpleNamespace(type="AIMessageChunk", content="一位候选人。", tool_call_chunks=[]), {}),
        )

    async def get_state_values(self, thread_id):
        return await self.ainvoke(
            messages=[{"role": "user", "content": "找 Python 候选人"}],
            thread_id=thread_id,
        )


class FailingHRAssistantAgent(FakeHRAssistantAgent):
    """模拟模型流执行失败。"""

    async def astream(self, *, messages, thread_id):
        if False:
            yield None
        raise RuntimeError("模拟模型连接失败")


@pytest.mark.asyncio
async def test_send_message_persists_user_answer_and_tool_summary(monkeypatch):
    """一轮对话应分别保存用户消息、最终回答和脱敏工具摘要。"""

    FakeConversationRepo.created_messages = []
    monkeypatch.setattr(conversation_module, "AsyncSessionFactory", lambda: FakeSessionFactory())
    monkeypatch.setattr(conversation_module, "AssistantConversationRepo", FakeConversationRepo)
    monkeypatch.setattr(conversation_module, "HRAssistantAgent", FakeHRAssistantAgent)

    result = await HRAssistantConversationService().send_message(
        user_id="hr-1",
        conversation_id="conversation-1",
        content="找 Python 候选人",
    )

    assert result["answer"] == "找到一位候选人。"
    assert result["artifacts"][0]["candidates"][0]["candidate_id"] == "candidate-1"
    assert FakeHRAssistantAgent.received_thread_id == "hr-assistant:hr-1:conversation-1"
    assert [item["role"].value for item in FakeConversationRepo.created_messages] == [
        "user",
        "assistant",
        "tool",
    ]
    assert FakeConversationRepo.created_messages[1]["metadata"]["candidate_ids"] == ["candidate-1"]
    assert FakeConversationRepo.created_messages[2]["metadata"] == {
        "artifact_type": "candidate_cards",
        "candidate_ids": ["candidate-1"],
    }


@pytest.mark.asyncio
async def test_send_message_hides_other_users_conversation(monkeypatch):
    """按会话 ID 查询时必须同时校验所有者。"""

    monkeypatch.setattr(conversation_module, "AsyncSessionFactory", lambda: FakeSessionFactory())
    monkeypatch.setattr(conversation_module, "AssistantConversationRepo", FakeConversationRepo)

    with pytest.raises(AssistantConversationNotFoundError):
        await HRAssistantConversationService().send_message(
            user_id="other-user",
            conversation_id="conversation-1",
            content="越权访问",
        )


@pytest.mark.asyncio
async def test_ensure_active_conversation_rejects_archived_conversation(monkeypatch):
    """SSE 路由预校验必须在模型调用前拒绝已归档会话。"""

    monkeypatch.setattr(conversation_module, "AsyncSessionFactory", lambda: FakeSessionFactory())
    monkeypatch.setattr(conversation_module, "AssistantConversationRepo", FakeConversationRepo)
    original_status = FakeConversationRepo.conversation.status
    FakeConversationRepo.conversation.status = AssistantConversationStatusEnum.ARCHIVED
    try:
        with pytest.raises(AssistantConversationInactiveError):
            await HRAssistantConversationService().ensure_active_conversation(
                user_id="hr-1",
                conversation_id="conversation-1",
            )
    finally:
        FakeConversationRepo.conversation.status = original_status


@pytest.mark.asyncio
async def test_stream_message_emits_text_tool_events_and_persists_final_turn(monkeypatch):
    """SSE 服务应输出过程事件，且只在结束后持久化最终助手消息。"""

    FakeConversationRepo.created_messages = []
    monkeypatch.setattr(conversation_module, "AsyncSessionFactory", lambda: FakeSessionFactory())
    monkeypatch.setattr(conversation_module, "AssistantConversationRepo", FakeConversationRepo)
    monkeypatch.setattr(conversation_module, "HRAssistantAgent", FakeHRAssistantAgent)

    events = [
        event
        async for event in HRAssistantConversationService().stream_message(
            user_id="hr-1",
            conversation_id="conversation-1",
            content="找 Python 候选人",
        )
    ]

    assert [event["event"] for event in events] == [
        "message_start",
        "tool_start",
        "content_delta",
        "tool_end",
        "content_delta",
        "message_end",
    ]
    assert events[1]["data"]["display"] == "正在检索人才库"
    assert events[-1]["data"]["answer"] == "找到一位候选人。"
    assert events[-1]["data"]["candidate_ids"] == ["candidate-1"]
    assert [item["role"].value for item in FakeConversationRepo.created_messages] == [
        "user",
        "assistant",
        "tool",
    ]


@pytest.mark.asyncio
async def test_stream_message_returns_error_without_persisting_success_message(monkeypatch):
    """模型流失败后只保留用户消息，不能写入伪造的助手成功记录。"""

    FakeConversationRepo.created_messages = []
    monkeypatch.setattr(conversation_module, "AsyncSessionFactory", lambda: FakeSessionFactory())
    monkeypatch.setattr(conversation_module, "AssistantConversationRepo", FakeConversationRepo)
    monkeypatch.setattr(conversation_module, "HRAssistantAgent", FailingHRAssistantAgent)

    events = [
        event
        async for event in HRAssistantConversationService().stream_message(
            user_id="hr-1",
            conversation_id="conversation-1",
            content="找 Python 候选人",
        )
    ]

    assert [event["event"] for event in events] == ["message_start", "error"]
    assert events[-1]["data"]["code"] == "assistant_stream_failed"
    assert [item["role"].value for item in FakeConversationRepo.created_messages] == ["user"]


def test_build_thread_id_contains_user_and_conversation():
    assert HRAssistantConversationService.build_thread_id("hr-1", "conversation-1") == (
        "hr-assistant:hr-1:conversation-1"
    )
