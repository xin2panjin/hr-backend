import json
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from services import interview_scheduling_service as scheduling_module
from services.interview_scheduling_service import InterviewSchedulingService


class FakeDingTalkHttp:
    calls = []

    async def get_calendar_list(self, **kwargs):
        self.calls.append(kwargs)
        return []


@pytest.mark.asyncio
async def test_get_available_slots_returns_iso_strings_from_tomorrow(monkeypatch):
    FakeDingTalkHttp.calls = []
    monkeypatch.setattr(scheduling_module, "DingTalkHttp", FakeDingTalkHttp)

    service = InterviewSchedulingService()
    service._get_interviewer_union_id = AsyncMock(return_value="union-1")
    service.get_dingtalk_access_token = AsyncMock(return_value="token-1")

    result = await service.get_available_slots(SimpleNamespace(id="interviewer-1"))

    assert result.startswith("找到面试官可用的时间：")
    slots = json.loads(result.split("：", 1)[1])
    first_start = datetime.fromisoformat(slots[0][0])
    assert first_start.hour == 9
    assert first_start.date() == datetime.now().date() + timedelta(days=1)
    assert first_start.utcoffset() == timedelta(hours=8)
    assert FakeDingTalkHttp.calls[0]["union_id"] == "union-1"


def test_as_naive_beijing_normalizes_timezone():
    result = InterviewSchedulingService._as_naive_beijing(
        "2026-07-02T01:00:00+00:00"
    )

    assert result == datetime(2026, 7, 2, 9, 0, 0)
    assert result.tzinfo is None
