from typing import Any

from langchain.agents import create_agent
from langchain.agents.middleware import ModelFallbackMiddleware, SummarizationMiddleware

from agents.llms import deepseek_llm, qwen_llm

from .prompts import HR_ASSISTANT_SYSTEM_PROMPT
from .state import HRAssistantState
from .tools import HR_ASSISTANT_TOOLS


def build_hr_assistant_agent(checkpointer: Any):
    """组装 HR 招聘助手 Agent。"""

    return create_agent(
        model=deepseek_llm,
        system_prompt=HR_ASSISTANT_SYSTEM_PROMPT,
        state_schema=HRAssistantState,
        middleware=[
            ModelFallbackMiddleware(first_model=qwen_llm),
            SummarizationMiddleware(
                model=deepseek_llm,
                trigger=("tokens", 50_000),
                keep=("tokens", 10_000),
            ),
        ],
        tools=HR_ASSISTANT_TOOLS,
        checkpointer=checkpointer,
    )