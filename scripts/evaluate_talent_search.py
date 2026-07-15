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

from sqlalchemy import func, select

from models import AsyncSessionFactory
from models.candidate import CandidateStatusEnum
from models.candidate_search import CandidateSearchProfileModel
from rag.talent_search_evaluation import (
    DEFAULT_EVALUATION_CASES_PATH,
    build_experiment_snapshot,
    build_evaluation_summary,
    calculate_ranking_metrics,
    load_evaluation_cases,
    render_markdown_report,
)
from rag.retrieval_types import RetrievalMode
from repository.candidate_repo import CandidateRepo
from repository.iam_repo import IamRepo
from repository.user_repo import UserRepo
from services.talent_search_service import TalentSearchService
from settings import settings


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
        help="可选：将评测报告写入指定 JSON 文件；同时默认生成同名 Markdown 文件",
    )
    parser.add_argument(
        "--markdown-output",
        type=Path,
        help="可选：指定 Markdown 评测报告路径",
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


async def get_evaluation_user(*, session, user_id: str):
    """加载评测用户及其有效 IAM 角色，保持与接口鉴权的权限上下文一致。"""

    user = await UserRepo(session).get_by_id(user_id)
    if not user:
        raise ValueError("评测用户不存在，请检查 --user-id")

    # CandidatePolicy 依赖 iam_roles 计算 Milvus 预过滤和 PostgreSQL 二次复核范围。
    # 脚本若只加载 users 表，会把管理员错误判定为无候选人访问权限。
    user.iam_roles = await IamRepo(session).get_active_user_roles(user.id)
    return user


async def get_profile_snapshot(*, session) -> dict[str, int]:
    """记录候选人画像快照，不读取完整简历或任何敏感字段。"""

    profile_count, max_profile_version, indexed_count = (await session.execute(
        select(
            func.count(CandidateSearchProfileModel.id),
            func.coalesce(func.max(CandidateSearchProfileModel.profile_version), 0),
            func.count(CandidateSearchProfileModel.id).filter(
                CandidateSearchProfileModel.indexed_version.is_not(None)
            ),
        )
    )).one()
    return {
        "profile_count": int(profile_count),
        "max_profile_version": int(max_profile_version),
        "indexed_profile_count": int(indexed_count),
    }


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
    profile_snapshot = None
    async with AsyncSessionFactory() as session:
        user = await get_evaluation_user(session=session, user_id=args.user_id)
        profile_snapshot = await get_profile_snapshot(session=session)

        service = TalentSearchService(candidate_repo=CandidateRepo(session))
        for case in cases:
            for mode in RetrievalMode:
                started_at = perf_counter()
                try:
                    trace = await service.search_with_trace(
                        query=case.query,
                        current_user=user,
                        top_k=case.top_k,
                        position_id=args.position_id,
                        status=parse_status(case.status),
                        retrieval_mode=mode,
                    )
                    retrieval_candidate_ids = [hit.candidate_id for hit in trace.retrieved_hits]
                    rerank_candidate_ids = [hit.candidate_id for hit in trace.reranked_hits]
                    final_candidate_ids = [item["candidate_id"] for item in trace.results]
                    report_items.append({
                            "case_id": case.case_id,
                            "query": case.query,
                            "focus": case.focus,
                            "mode": mode.value,
                            "relevant_candidate_ids": list(case.relevant_candidate_ids),
                            "expect_empty_result": case.expect_empty_result,
                            "retrieval": {
                                "candidate_ids": retrieval_candidate_ids,
                                "scores": [round(float(hit.score), 6) for hit in trace.retrieved_hits],
                                "latency_ms": round(trace.retrieval_elapsed_ms, 2),
                            },
                            "rerank": {
                                "candidate_ids": rerank_candidate_ids,
                                "scores": [round(float(hit.score), 6) for hit in trace.reranked_hits],
                                "elapsed_ms": round(trace.rerank_elapsed_ms, 2),
                            },
                            "final": {
                                "candidate_ids": final_candidate_ids,
                                "scores": [round(float(item["score"]), 6) for item in trace.results],
                                "finalization_elapsed_ms": round(trace.finalization_elapsed_ms, 2),
                                "total_elapsed_ms": round(trace.total_elapsed_ms, 2),
                            },
                            "metrics": {
                                "retrieval": calculate_ranking_metrics(retrieval_candidate_ids, case.relevant_candidate_ids, case.top_k),
                                "rerank": calculate_ranking_metrics(rerank_candidate_ids, case.relevant_candidate_ids, case.top_k),
                                "final": calculate_ranking_metrics(final_candidate_ids, case.relevant_candidate_ids, case.top_k),
                            },
                            "error": None,
                        })
                except Exception as exc:
                    report_items.append({
                            "case_id": case.case_id,
                            "query": case.query,
                            "focus": case.focus,
                            "mode": mode.value,
                            "relevant_candidate_ids": list(case.relevant_candidate_ids),
                            "expect_empty_result": case.expect_empty_result,
                            "retrieval": {"candidate_ids": [], "scores": [], "latency_ms": round((perf_counter() - started_at) * 1000, 2)},
                            "rerank": {"candidate_ids": [], "scores": [], "elapsed_ms": 0.0},
                            "final": {"candidate_ids": [], "scores": [], "finalization_elapsed_ms": 0.0, "total_elapsed_ms": round((perf_counter() - started_at) * 1000, 2)},
                            "metrics": {stage: calculate_ranking_metrics([], case.relevant_candidate_ids, case.top_k) for stage in ("retrieval", "rerank", "final")},
                            # 底层异常文本可能拼接查询或数据库条件，因此报告只记录类型。
                            "error": type(exc).__name__,
                        })

    report = {
        "schema_version": 3,
        "cases_file": str(args.cases_file),
        "item_count": len(report_items),
        "experiment_snapshot": build_experiment_snapshot(
            cases_file=args.cases_file,
            settings=settings,
            profile_snapshot=profile_snapshot or {},
        ),
        "items": report_items,
    }
    report["summary"] = build_evaluation_summary(report_items)
    rendered_report = json.dumps(report, ensure_ascii=False, indent=2)
    print(rendered_report)

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered_report + "\n", encoding="utf-8")
        print(f"评测报告已写入：{args.output}")

    markdown_output = args.markdown_output or (args.output.with_suffix(".md") if args.output else None)
    if markdown_output:
        markdown_output.parent.mkdir(parents=True, exist_ok=True)
        markdown_output.write_text(render_markdown_report(report), encoding="utf-8")
        print(f"Markdown 评测报告已写入：{markdown_output}")


if __name__ == "__main__":
    asyncio.run(main())
