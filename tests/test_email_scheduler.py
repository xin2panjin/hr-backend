from types import SimpleNamespace

import pytest

import scheduler as scheduler_module
from services.candidate_workflow_service import CandidateEmailNotFoundError


class FakeCache:
    saved_uids = []

    async def set_email_last_uid(self, uid):
        self.saved_uids.append(uid)


class FakeEmailBot:
    def __init__(self, emails):
        self.emails = emails
        self.settings = SimpleNamespace(email="hr@example.com")

    async def fetch_since_uid(self, uid):
        return self.emails


def build_email(uid, sender, content="邮件内容"):
    return SimpleNamespace(
        uid=str(uid),
        from_=SimpleNamespace(address=sender),
        text=content,
        html="",
    )


@pytest.mark.asyncio
async def test_unknown_sender_is_skipped_and_uid_is_advanced(monkeypatch):
    """账单等非候选人邮件不能反复阻塞邮箱轮询。"""

    class FakeWorkflowService:
        calls = []

        async def on_candidate_email_received(self, from_email, content):
            self.calls.append(from_email)
            raise CandidateEmailNotFoundError("未找到邮箱对应的候选人")

    FakeCache.saved_uids = []
    monkeypatch.setattr(scheduler_module, "CandidateWorkflowService", FakeWorkflowService)
    monkeypatch.setattr(scheduler_module, "HRCache", FakeCache)
    bot = FakeEmailBot([build_email(101, "wxad_statement@tencent.com")])
    state = {"last_uid": 100}

    await scheduler_module.poll_and_process_emails(bot, state)

    assert FakeWorkflowService.calls == ["wxad_statement@tencent.com"]
    assert state["last_uid"] == 101
    assert FakeCache.saved_uids == [101]


@pytest.mark.asyncio
async def test_unknown_sender_does_not_block_later_candidate_email(monkeypatch):
    """跳过非候选人邮件后，同一批次中的候选人回复仍应继续处理。"""

    class FakeWorkflowService:
        calls = []

        async def on_candidate_email_received(self, from_email, content):
            self.calls.append(from_email)
            if from_email == "notice@example.com":
                raise CandidateEmailNotFoundError("未找到邮箱对应的候选人")
            return {"result": "ok"}

    FakeCache.saved_uids = []
    monkeypatch.setattr(scheduler_module, "CandidateWorkflowService", FakeWorkflowService)
    monkeypatch.setattr(scheduler_module, "HRCache", FakeCache)
    bot = FakeEmailBot(
        [
            build_email(101, "notice@example.com"),
            build_email(102, "candidate@example.com"),
        ]
    )
    state = {"last_uid": 100}

    await scheduler_module.poll_and_process_emails(bot, state)

    assert FakeWorkflowService.calls == ["notice@example.com", "candidate@example.com"]
    assert state["last_uid"] == 102
    assert FakeCache.saved_uids == [101, 102]


@pytest.mark.asyncio
async def test_processing_error_keeps_uid_for_later_retry(monkeypatch):
    """候选人邮件处理失败时不推进游标，防止邮件被静默丢弃。"""

    class FakeWorkflowService:
        async def on_candidate_email_received(self, from_email, content):
            raise RuntimeError("temporary failure")

    FakeCache.saved_uids = []
    monkeypatch.setattr(scheduler_module, "CandidateWorkflowService", FakeWorkflowService)
    monkeypatch.setattr(scheduler_module, "HRCache", FakeCache)
    bot = FakeEmailBot([build_email(101, "candidate@example.com")])
    state = {"last_uid": 100}

    await scheduler_module.poll_and_process_emails(bot, state)

    assert state["last_uid"] == 100
    assert FakeCache.saved_uids == []
