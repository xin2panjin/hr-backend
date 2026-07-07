from agents.hr_assistant.tools.talent_search import _parse_status
from models.candidate import CandidateStatusEnum


def test_parse_status_by_value():
    assert _parse_status("已投递") == CandidateStatusEnum.APPLICATION


def test_parse_status_by_name():
    assert _parse_status("APPLICATION") == CandidateStatusEnum.APPLICATION


def test_parse_status_unknown_returns_none():
    assert _parse_status("不存在的状态") is None