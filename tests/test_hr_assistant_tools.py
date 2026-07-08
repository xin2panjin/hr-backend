from agents.hr_assistant.tools.talent_search import _parse_status
from agents.hr_assistant.tools.candidate_detail import _build_candidate_detail
from agents.hr_assistant.tools.candidate_compare import _build_candidate_compare_payload
from models.candidate import CandidateStatusEnum
from types import SimpleNamespace

def test_parse_status_by_value():
    assert _parse_status("已投递") == CandidateStatusEnum.APPLICATION


def test_parse_status_by_name():
    assert _parse_status("APPLICATION") == CandidateStatusEnum.APPLICATION


def test_parse_status_unknown_returns_none():
    assert _parse_status("不存在的状态") is None

def test_build_candidate_detail_hides_sensitive_fields():
    candidate = SimpleNamespace(
        id="candidate-1",
        name="张三",
        gender=SimpleNamespace(value="男"),
        status=SimpleNamespace(value="已投递"),
        email="secret@example.com",
        phone_number="13800000000",
        birthday="1990-01-01",
        skills="Python, FastAPI, Milvus",
        work_experience="5年后端开发经验",
        project_experience="做过RAG项目",
        education_experience="本科",
        self_evaluation="学习能力强",
        other_information="无",
        position=SimpleNamespace(
            id="position-1",
            title="后端开发工程师",
            requirements="熟悉 Python",
            department=SimpleNamespace(name="技术部"),
        ),
        ai_score=None,
    )

    detail = _build_candidate_detail(candidate)

    assert detail["candidate_id"] == "candidate-1"
    assert detail["name"] == "张三"
    assert detail["profile"]["skills"] == "Python, FastAPI, Milvus"

    # 工具返回中不应该包含敏感字段。
    assert "email" not in detail
    assert "phone_number" not in detail
    assert "birthday" not in detail

def test_build_candidate_compare_payload_hides_sensitive_fields():
    candidate = SimpleNamespace(
        id="candidate-1",
        name="张三",
        gender=SimpleNamespace(value="男"),
        status=SimpleNamespace(value="已投递"),
        email="secret@example.com",
        phone_number="13800000000",
        birthday="1990-01-01",
        skills="Python, FastAPI, Milvus",
        work_experience="5年后端开发经验",
        project_experience="做过RAG项目",
        education_experience="本科",
        self_evaluation="学习能力强",
        other_information="无",
        position=SimpleNamespace(
            id="position-1",
            title="后端开发工程师",
            requirements="熟悉 Python",
            department=SimpleNamespace(name="技术部"),
        ),
        ai_score=None,
    )

    payload = _build_candidate_compare_payload(
        candidates=[candidate],
        requested_candidate_ids=["candidate-1", "candidate-2"],
    )

    assert payload["count"] == 1
    assert payload["missing_candidate_ids"] == ["candidate-2"]

    candidate_detail = payload["candidates"][0]
    assert candidate_detail["candidate_id"] == "candidate-1"
    assert candidate_detail["name"] == "张三"

    # 对比工具也不能暴露敏感字段。
    assert "email" not in candidate_detail
    assert "phone_number" not in candidate_detail
    assert "birthday" not in candidate_detail