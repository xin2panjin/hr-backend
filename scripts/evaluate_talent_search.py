"""执行人才库 dense、sparse、hybrid 三种检索模式的离线对比评测。

执行示例：
    uv run python -m scripts.evaluate_talent_search --user-id <用户ID>
    uv run python -m scripts.evaluate_talent_search --user-id <用户ID> --case-id acronym_rag
    uv run python -m scripts.evaluate_talent_search --user-id <用户ID> --output output/talent-search.json
"""

import argparse
import asyncio
import json
from pathlib import Path
from time import perf_counter

from models import AsyncSessionFactory
from models.candidate import CandidateStatusEnum
from rag.talent_search_evaluation import (
    DEFAULT_EVALUATION_CASES_PATH,
    load_evaluation_cases,
)
from rag.retrieval_types import RetrievalMode
from repository.candidate_repo import CandidateRepo
from repository.user_repo import UserRepo
from services.talent_search_service import TalentSearchService


def parse_args() -> argparse.Namespace:
    """解析离线评测命令参数。"""

    parser = argparse.ArgumentParser(description="评测人才库的 dense、sparse、hybrid 检索")
    parser.add_argument("--user-id", required=True, help="用于权限校验的现有系统用户 ID")
    parser.add_argument(
        "--case-id",
        action="append",
        default=[],
        help="仅运行指定样本；可重复传入多个 case_id",
    )
    parser.add_argument(
        "--cases-file",
        type=Path,
        default=DEFAULT_EVALUATION_CASES_PATH,
        help="评测查询集 JSON 文件路径",
    )
    parser.add_argument(
        "--position-id",
        help="可选：为所有评测样本附加同一个职位过滤条件",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="可选：将脱敏评测报告写入指定 JSON 文件",
    )
    return parser.parse_args()


def parse_status(status: str | None) -> CandidateStatusEnum | None:
    """将评测集中的状态值转换为业务枚举。"""

    if status is None:
        return None
    for item in CandidateStatusEnum:
        if status == item.value or status == item.name:
            return item
    raise ValueError(f"评测样本包含未知候选人状态：{status}")


async def main() -> None:
    """加载样本并生成三种检索模式的对比报告。"""

    args = parse_args()
    cases = load_evaluation_cases(args.cases_file)
    requested_case_ids = set(args.case_id)
    if requested_case_ids:
        cases = [case for case in cases if case.case_id in requested_case_ids]
        missing_case_ids = requested_case_ids - {case.case_id for case in cases}
        if missing_case_ids:
            raise ValueError(f"未找到评测样本：{', '.join(sorted(missing_case_ids))}")

    report_items = []
    async with AsyncSessionFactory() as session:
        user = await UserRepo(session).get_by_id(args.user_id)
        if not user:
            raise ValueError("评测用户不存在，请检查 --user-id")

        service = TalentSearchService(candidate_repo=CandidateRepo(session))
        for case in cases:
            for mode in RetrievalMode:
                started_at = perf_counter()
                try:
                    candidates = await service.search(
                        query=case.query,
                        current_user=user,
                        top_k=case.top_k,
                        position_id=args.position_id,
                        status=parse_status(case.status),
                        retrieval_mode=mode,
                    )
                    report_items.append(
                        {
                            "case_id": case.case_id,
                            "focus": case.focus,
                            "mode": mode.value,
                            "latency_ms": round((perf_counter() - started_at) * 1000, 2),
                            "candidate_ids": [item["candidate_id"] for item in candidates],
                            "scores": [round(float(item["score"]), 6) for item in candidates],
                            "error": None,
                        }
                    )
                except Exception as exc:
                    report_items.append(
                        {
                            "case_id": case.case_id,
                            "focus": case.focus,
                            "mode": mode.value,
                            "latency_ms": round((perf_counter() - started_at) * 1000, 2),
                            "candidate_ids": [],
                            "scores": [],
                            # 底层异常文本可能拼接查询或数据库条件，因此报告只记录类型。
                            "error": type(exc).__name__,
                        }
                    )

    report = {
        "cases_file": str(args.cases_file),
        "item_count": len(report_items),
        "items": report_items,
    }
    rendered_report = json.dumps(report, ensure_ascii=False, indent=2)
    print(rendered_report)

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered_report + "\n", encoding="utf-8")
        print(f"评测报告已写入：{args.output}")


if __name__ == "__main__":
    asyncio.run(main())
