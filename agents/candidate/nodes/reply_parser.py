from datetime import datetime
from typing import Any, Literal

from langchain.agents import create_agent
from langchain.agents.middleware import ModelFallbackMiddleware
from langchain_core.messages import BaseMessage
from langchain_core.prompts import PromptTemplate
from pydantic import BaseModel, Field

from agents.llms import deepseek_llm, qwen_llm

from ..prompts import (
    PARSE_CANDIDATE_REPLY_SYSTEM_PROMPT,
    PARSE_CANDIDATE_REPLY_USER_PROMPT,
)
from ..state import CandidateProcessStage, CandidateReplyIntent
from .context import get_state_value


class CandidateReplyParseResult(BaseModel):
    """候选人邮件回复解析结果。"""

    intent: Literal["confirm", "reschedule", "refuse", "unclear"] = Field(
        ..., description="候选人对面试安排的回复意图"
    )
    requested_time: str | None = Field(None, description="候选人提出的新面试时间")
    reason: str | None = Field(None, description="候选人说明的原因")
    confidence: float = Field(..., ge=0, le=1, description="解析置信度")


reply_parser_agent = create_agent(
    model=qwen_llm,
    system_prompt=PARSE_CANDIDATE_REPLY_SYSTEM_PROMPT,
    middleware=[ModelFallbackMiddleware(first_model=deepseek_llm)],
    response_format=CandidateReplyParseResult,
)


def _get_latest_message_content(state: Any) -> str:
    """从累计 messages 中取出本轮最新消息文本。"""
    messages = get_state_value(state, "messages") or []
    if not messages:
        return ""

    latest_message = messages[-1]
    if isinstance(latest_message, dict):
        return str(latest_message.get("content") or "")
    if isinstance(latest_message, BaseMessage):
        return str(latest_message.content or "")
    return str(getattr(latest_message, "content", "") or "")


async def parse_candidate_reply_node(state: Any) -> dict:
    """解析候选人邮件回复，并把结构化意图写入轻量 State。"""
    message = _get_latest_message_content(state)
    if not message:
        return {
            "stage": CandidateProcessStage.NEED_HUMAN_REVIEW,
            "need_human_review": True,
            "last_error": "解析候选人回复失败：没有找到邮件内容",
        }

    try:
        prompt = PromptTemplate.from_template(PARSE_CANDIDATE_REPLY_USER_PROMPT).invoke(
            {
                "current_time": datetime.now().isoformat(),
                "message": message,
            }
        )
        response = await reply_parser_agent.ainvoke(
            {"messages": [{"role": "user", "content": prompt.text}]}
        )
        result: CandidateReplyParseResult = response["structured_response"]
        return {
            "stage": CandidateProcessStage.REPLY_PARSED,
            "candidate_reply_intent": CandidateReplyIntent(result.intent),
            "candidate_requested_time": result.requested_time,
            "last_error": None,
            "need_human_review": False,
        }
    except Exception as exc:
        return {
            "stage": CandidateProcessStage.NEED_HUMAN_REVIEW,
            "need_human_review": True,
            "last_error": f"解析候选人回复失败：{exc}",
        }
