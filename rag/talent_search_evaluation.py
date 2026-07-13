"""人才检索离线评测查询集的加载与校验。"""

import json
from dataclasses import dataclass
from pathlib import Path


DEFAULT_EVALUATION_CASES_PATH = (
    Path(__file__).resolve().parents[1]
    / "docs"
    / "人才库检索评测查询集.json"
)


@dataclass(frozen=True, slots=True)
class TalentSearchEvaluationCase:
    """一条可在 dense、sparse、hybrid 下重复运行的查询样本。"""

    case_id: str
    query: str
    focus: str
    top_k: int = 10
    status: str | None = None


def load_evaluation_cases(
    path: Path = DEFAULT_EVALUATION_CASES_PATH,
) -> list[TalentSearchEvaluationCase]:
    """加载并校验评测查询集，避免错误样本进入对比报告。"""

    raw_cases = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw_cases, list) or not raw_cases:
        raise ValueError("评测查询集必须是非空 JSON 数组")

    cases: list[TalentSearchEvaluationCase] = []
    case_ids: set[str] = set()
    for index, raw_case in enumerate(raw_cases, start=1):
        if not isinstance(raw_case, dict):
            raise ValueError(f"第 {index} 条评测样本必须是对象")

        case_id = str(raw_case.get("case_id", "")).strip()
        query = str(raw_case.get("query", "")).strip()
        focus = str(raw_case.get("focus", "")).strip()
        top_k = raw_case.get("top_k", 10)
        status = raw_case.get("status")

        if not case_id or not query or not focus:
            raise ValueError(f"第 {index} 条评测样本缺少 case_id、query 或 focus")
        if case_id in case_ids:
            raise ValueError(f"评测样本 case_id 重复：{case_id}")
        if not isinstance(top_k, int) or not 1 <= top_k <= 50:
            raise ValueError(f"评测样本 {case_id} 的 top_k 必须在 1 到 50 之间")
        if status is not None and not isinstance(status, str):
            raise ValueError(f"评测样本 {case_id} 的 status 必须是字符串")

        case_ids.add(case_id)
        cases.append(
            TalentSearchEvaluationCase(
                case_id=case_id,
                query=query,
                focus=focus,
                top_k=top_k,
                status=status,
            )
        )

    return cases
