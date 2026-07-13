"""HR 招聘助手会话服务的核心流程测试。"""

import json
from types import SimpleNamespace

import pytest

from models.assistant_conversation import AssistantConversationStatusEnum
from services import hr_assistant_conversation_service as conversation_module
from services.hr_assistant_conversation_service import (
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


def test_build_thread_id_contains_user_and_conversation():
    assert HRAssistantConversationService.build_thread_id("hr-1", "conversation-1") == (
        "hr-assistant:hr-1:conversation-1"
    )
