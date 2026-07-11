"""简历解析 Agent 包，对外统一暴露结构化提取函数。"""

from .agent import extract_candidate_info

__all__ = ["extract_candidate_info"]