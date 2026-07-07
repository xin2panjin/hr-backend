from typing import Any

from langchain.agents import create_agent
from langchain.agents.middleware import ModelFallbackMiddleware, SummarizationMiddleware

from agents.llms import deepseek_llm, qwen_llm

from .prompts import CANDIDATE_PROCESS_SYSTEM_PROMPT
from .state import CandidateAgentState
from .tools import CANDIDATE_TOOLS


def build_candidate_agent(checkpointer: Any):
    """组装基于 LangGraph 的候选人 Agent，并注入工具和状态存储。"""
    return create_agent(
        model=deepseek_llm,
        system_prompt=CANDIDATE_PROCESS_SYSTEM_PROMPT,
        state_schema=CandidateAgentState,
        middleware=[
            # DeepSeek 调用异常时自动降级到 Qwen，避免单一模型故障中断流程。
            ModelFallbackMiddleware(first_model=qwen_llm),
            # 长邮件会话超过阈值后压缩历史消息，控制上下文和 Token 消耗。
            SummarizationMiddleware(
                model=deepseek_llm,
                trigger=("tokens", 50_000),
                keep=("tokens", 10_000),
            ),
        ],
        tools=CANDIDATE_TOOLS,
        checkpointer=checkpointer,
    )
