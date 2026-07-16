from agents.hr_assistant.tools.talent_search import _parse_status
from agents.hr_assistant.tools.candidate_detail import _build_candidate_detail
from agents.hr_assistant.tools.candidate_compare import _build_candidate_compare_payload
from agents.hr_assistant.tools.knowledge_search import (
    _build_knowledge_sources_payload,
    _load_authorized_user,
    search_recruiting_knowledge,
)
from agents.hr_assistant.tools.user_context import load_user_with_active_roles
from iam.policies.candidate_policy import CandidatePolicy, CandidateScopeType
from iam.permissions import RoleCode
from agents.hr_assistant.tools import HR_ASSISTANT_TOOLS
from models.candidate import CandidateStatusEnum
from services.hr_assistant_conversation_service import HRAssistantConversationService
from types import SimpleNamespace
import json
import pytest


def _extract_hr_assistant_artifacts(messages):
    """兼容旧兼容层测试：产物提取已下沉到会话服务。"""

    return HRAssistantConversationService._extract_artifacts(messages)


def _get_current_turn_messages(messages):
    return HRAssistantConversationService._get_current_turn_messages(messages)


def test_parse_status_by_value():
    assert _parse_status("已投递") == CandidateStatusEnum.APPLICATION


def test_parse_status_by_name():
    assert _parse_status("APPLICATION") == CandidateStatusEnum.APPLICATION


def test_parse_status_unknown_returns_none():
    assert _parse_status("不存在的状态") is None


def test_knowledge_search_tool_is_registered_and_serializes_sources():
    assert any(tool.name == "search_recruiting_knowledge" for tool in HR_ASSISTANT_TOOLS)
    source = type("Source", (), {"to_dict": lambda self: {"source_id": "chunk-1"}})()
    result = type(
        "SearchResult",
        (),
        {
            "knowledge_base_key": "recruiting_policy",
            "retrieval_mode": type("Mode", (), {"value": "hybrid"})(),
            "trace_id": "trace-1",
            "sources": [source],
        },
    )()

    payload = _build_knowledge_sources_payload(result)

    assert payload["artifact_type"] == "knowledge_sources"
    assert payload["count"] == 1
    assert payload["sources"] == [{"source_id": "chunk-1"}]


@pytest.mark.asyncio
async def test_knowledge_search_tool_validates_input_before_accessing_database():
    class Runtime:
        state = {"current_user_id": "user-1"}

    result = await search_recruiting_knowledge.coroutine(
        query="年假",
        runtime=Runtime(),
        top_k=0,
    )

    assert "1 到 20" in result


@pytest.mark.asyncio
async def test_knowledge_search_permission_check_rejects_user_without_assistant_access():
    class FakeUserRepo:
        def __init__(self, session):
            self.session = session

        async def get_by_id(self, user_id):
            return SimpleNamespace(id=user_id)

    class FakeIamRepo:
        def __init__(self, session):
            self.session = session

        async def get_active_user_roles(self, user_id):
            return [
                SimpleNamespace(
                    role=SimpleNamespace(
                        permissions=[SimpleNamespace(code="candidate.read")]
                    )
                )
            ]

    import agents.hr_assistant.tools.knowledge_search as knowledge_tool_module

    original_user_repo = knowledge_tool_module.UserRepo
    original_iam_repo = knowledge_tool_module.IamRepo
    knowledge_tool_module.UserRepo = FakeUserRepo
    knowledge_tool_module.IamRepo = FakeIamRepo
    try:
        user, error = await _load_authorized_user(object(), "employee-1")
    finally:
        knowledge_tool_module.UserRepo = original_user_repo
        knowledge_tool_module.IamRepo = original_iam_repo

    assert user is None
    assert error == "当前用户没有使用企业制度知识库的权限。"


@pytest.mark.asyncio
async def test_load_user_with_active_roles_preserves_system_admin_candidate_scope():
    user = SimpleNamespace(id="admin-1")

    class FakeUserRepo:
        def __init__(self, session):
            self.session = session

        async def get_by_id(self, user_id):
            assert user_id == "admin-1"
            return user

    class FakeIamRepo:
        def __init__(self, session):
            self.session = session

        async def get_active_user_roles(self, user_id):
            assert user_id == "admin-1"
            return [
                SimpleNamespace(
                    role=SimpleNamespace(code=RoleCode.SYSTEM_ADMIN.value),
                    scopes=[],
                )
            ]

    import agents.hr_assistant.tools.user_context as user_context_module

    original_user_repo = user_context_module.UserRepo
    original_iam_repo = user_context_module.IamRepo
    user_context_module.UserRepo = FakeUserRepo
    user_context_module.IamRepo = FakeIamRepo
    try:
        loaded_user = await load_user_with_active_roles(object(), "admin-1")
    finally:
        user_context_module.UserRepo = original_user_repo
        user_context_module.IamRepo = original_iam_repo

    assert loaded_user is user
    assert CandidatePolicy.resolve_scope(loaded_user).type == CandidateScopeType.ALL

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
    assert "gender" not in detail
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

def test_extract_artifacts_from_search_tool_message():
    message = SimpleNamespace(
        type="tool",
        content=json.dumps(
            {
                "artifact_type": "candidate_cards",
                "candidates": [
                    {
                        "candidate_id": "candidate-1",
                        "name": "张三",
                        "position_title": "后端开发工程师",
                        "status": "AI筛选通过",
                        "score": 0.86,
                        "profile_text": "熟悉 Python 和 Milvus",
                    }
                ],
                "count": 1,
            },
            ensure_ascii=False,
        ),
    )

    artifacts = _extract_hr_assistant_artifacts([message])

    assert len(artifacts) == 1
    assert artifacts[0]["type"] == "candidate_cards"
    assert artifacts[0]["candidates"][0]["candidate_id"] == "candidate-1"
    assert artifacts[0]["candidates"][0]["actions"][0] == {
        "type": "open_candidate_detail",
        "label": "查看详情",
        "candidate_id": "candidate-1",
    }


def test_extract_artifacts_from_knowledge_search_tool_message():
    message = SimpleNamespace(
        type="tool",
        content=json.dumps(
            {
                "artifact_type": "knowledge_sources",
                "knowledge_base_key": "recruiting_policy",
                "trace_id": "trace-1",
                "sources": [
                    {
                        "source_id": "chunk-1",
                        "document_id": "doc-1",
                        "title": "员工休假管理制度",
                        "version": "V2",
                        "section_path": "第三章 > 年假",
                        "page_number": 5,
                        "page_end": 6,
                        "score": 0.9,
                        "content": "年假规则正文",
                        "chunk_ids": ["chunk-1", "chunk-2"],
                    }
                ],
            },
            ensure_ascii=False,
        ),
    )

    artifacts = _extract_hr_assistant_artifacts([message])

    assert len(artifacts) == 1
    assert artifacts[0]["type"] == "knowledge_sources"
    assert artifacts[0]["sources"][0]["section_path"] == "第三章 > 年假"
    assert artifacts[0]["sources"][0]["page_end"] == 6

def test_extract_artifacts_from_candidate_detail_tool_message():
    message = SimpleNamespace(
        type="tool",
        content=json.dumps(
            {
                "artifact_type": "candidate_detail",
                "candidate_id": "candidate-1",
                "name": "张三",
                "status": "已投递",
                "position": {
                    "id": "position-1",
                    "title": "后端开发工程师",
                    "department": "技术部",
                },
                "ai_score": {
                    "summary": "后端基础扎实，有 RAG 项目经验",
                },
            },
            ensure_ascii=False,
        ),
    )

    artifacts = _extract_hr_assistant_artifacts([message])

    assert len(artifacts) == 1
    assert artifacts[0]["type"] == "candidate_detail"
    assert artifacts[0]["candidates"][0]["candidate_id"] == "candidate-1"
    assert artifacts[0]["candidates"][0]["position_title"] == "后端开发工程师"
    assert artifacts[0]["candidates"][0]["actions"][0]["type"] == "open_candidate_detail"

def test_extract_artifacts_only_from_current_turn_messages():
    old_tool_message = SimpleNamespace(
        type="tool",
        content=json.dumps(
            {
                "artifact_type": "candidate_cards",
                "candidates": [
                    {
                        "candidate_id": "old-candidate",
                        "name": "旧候选人",
                        "position_title": "后端开发工程师",
                    }
                ],
                "count": 1,
            },
            ensure_ascii=False,
        ),
    )
    current_tool_message = SimpleNamespace(
        type="tool",
        content=json.dumps(
            {
                "artifact_type": "candidate_cards",
                "candidates": [
                    {
                        "candidate_id": "new-candidate",
                        "name": "新候选人",
                        "position_title": "大模型算法工程师",
                    }
                ],
                "count": 1,
            },
            ensure_ascii=False,
        ),
    )

    messages = [
        SimpleNamespace(type="human", content="帮我找后端候选人"),
        old_tool_message,
        SimpleNamespace(type="ai", content="找到旧候选人"),
        SimpleNamespace(type="human", content="再帮我找大模型候选人"),
        current_tool_message,
        SimpleNamespace(type="ai", content="找到新候选人"),
    ]

    current_turn_messages = _get_current_turn_messages(messages)
    artifacts = _extract_hr_assistant_artifacts(current_turn_messages)

    assert len(artifacts) == 1
    assert artifacts[0]["type"] == "candidate_cards"
    assert artifacts[0]["candidates"][0]["candidate_id"] == "new-candidate"

def test_extract_artifacts_from_candidate_comparison_tool_message():
    """候选人对比工具结果应被转换为前端可渲染的 artifact。"""

    message = SimpleNamespace(
        type="tool",
        content=json.dumps(
            {
                "artifact_type": "candidate_comparison",
                "candidates": [
                    {
                        "candidate_id": "candidate-1",
                        "name": "张三",
                        "status": "AI筛选通过",
                        "position": {"title": "大模型算法工程师"},
                        "ai_score": {
                            "overall_score": 9,
                            "summary": "RAG 与 Agent 项目经验丰富。",
                        },
                    },
                    {
                        "candidate_id": "candidate-2",
                        "name": "李四",
                        "status": "已投递",
                        "position": {"title": "后端开发工程师"},
                        "ai_score": {
                            "overall_score": 8,
                            "summary": "后端工程经验扎实。",
                        },
                    },
                ],
                "count": 2,
                "missing_candidate_ids": ["candidate-3"],
            },
            ensure_ascii=False,
        ),
    )

    artifacts = _extract_hr_assistant_artifacts([message])

    assert len(artifacts) == 1
    assert artifacts[0]["type"] == "candidate_comparison"
    assert len(artifacts[0]["candidates"]) == 2
    assert artifacts[0]["candidates"][0]["name"] == "张三"
    assert artifacts[0]["raw"]["missing_candidate_ids"] == ["candidate-3"]
