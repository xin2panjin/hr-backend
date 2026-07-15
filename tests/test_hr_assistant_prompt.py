"""HR 助手制度问答提示词回归测试。"""

from agents.hr_assistant.prompts import HR_ASSISTANT_SYSTEM_PROMPT
from agents.hr_assistant.tools import HR_ASSISTANT_TOOLS


def test_prompt_requires_recruiting_knowledge_tool_for_policy_questions():
    assert "search_recruiting_knowledge" in HR_ASSISTANT_SYSTEM_PROMPT
    assert "必须调用 search_recruiting_knowledge" in HR_ASSISTANT_SYSTEM_PROMPT
    assert "当前知识库未检索到相关制度依据" in HR_ASSISTANT_SYSTEM_PROMPT
    assert "sources" in HR_ASSISTANT_SYSTEM_PROMPT


def test_prompt_distinguishes_candidate_search_from_policy_search():
    prompt = HR_ASSISTANT_SYSTEM_PROMPT

    assert prompt.index("search_talent_pool") < prompt.index("search_recruiting_knowledge")
    assert "两类结果必须分开理解和表达" in prompt
    assert any(tool.name == "search_recruiting_knowledge" for tool in HR_ASSISTANT_TOOLS)
