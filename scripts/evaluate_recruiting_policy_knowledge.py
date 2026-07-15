"""执行企业制度知识库 dense、sparse、hybrid 检索评测。

执行示例：
    uv run python -m scripts.evaluate_recruiting_policy_knowledge
    uv run python -m scripts.evaluate_recruiting_policy_knowledge --case-id annual_leave_five_days
    uv run python -m scripts.evaluate_recruiting_policy_knowledge --output output/recruiting-policy-evaluation.json
"""

import argparse
import asyncio
import json
from pathlib import Path
from time import perf_counter

from knowledge.recruiting_policy import build_recruiting_policy_knowledge_base_definition
from rag.knowledge_search_evaluation import (
    DEFAULT_KNOWLEDGE_EVALUATION_CASES_PATH,
    build_knowledge_evaluation_summary,
    build_knowledge_experiment_snapshot,
    calculate_refusal_evidence_result,
    calculate_section_metrics,
    load_knowledge_evaluation_cases,
    render_knowledge_markdown_report,
)
from rag.retrieval_types import RetrievalMode
from services.knowledge_search_service import KnowledgeSearchService


def parse_args() -> argparse.Namespace:
    """解析可重复运行的制度检索评测参数。"""

    parser = argparse.ArgumentParser(description="评测企业制度知识库的 dense、sparse、hybrid 检索")
    parser.add_argument(
        "--case-id",
        action="append",
        default=[],
        help="仅运行指定样本；可重复传入多个 case_id",
    )
    parser.add_argument(
        "--cases-file",
        type=Path,
        default=DEFAULT_KNOWLEDGE_EVALUATION_CASES_PATH,
        help="评测集 JSON 文件路径",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="可选：写入 JSON 报告，并默认生成同名 Markdown 报告",
    )
    parser.add_argument(
        "--markdown-output",
        type=Path,
        help="可选：指定 Markdown 报告路径",
    )
    return parser.parse_args()


async def main() -> None:
    """对每条样本分别执行三种检索模式并输出可审计报告。"""

    args = parse_args()
    cases = load_knowledge_evaluation_cases(args.cases_file)
    requested_case_ids = set(args.case_id)
    if requested_case_ids:
        cases = [case for case in cases if case.case_id in requested_case_ids]
        missing_case_ids = requested_case_ids - {case.case_id for case in cases}
        if missing_case_ids:
            raise ValueError(f"未找到评测样本：{', '.join(sorted(missing_case_ids))}")

    definition = build_recruiting_policy_knowledge_base_definition()
    service = KnowledgeSearchService(knowledge_base_definition=definition)
    report_items: list[dict] = []
    for case in cases:
        for mode in RetrievalMode:
            started_at = perf_counter()
            try:
                result = await service.search(
                    query=case.query,
                    retrieval_mode=mode,
                    top_k=case.top_k,
                )
                source_sections = [
                    str(hit.metadata.get("section_path") or "")
                    for hit in result.hits
                ]
                metrics = calculate_section_metrics(
                    source_sections,
                    case.expected_source_sections,
                    case.top_k,
                )
                report_items.append(
                    {
                        "case_id": case.case_id,
                        "query": case.query,
                        "focus": case.focus,
                        "mode": mode.value,
                        "expected_source_sections": list(case.expected_source_sections),
                        "expected_refusal": case.expected_refusal,
                        "retrieval_elapsed_ms": round(result.elapsed_ms, 2),
                        "reranked": result.reranked,
                        "rerank_elapsed_ms": round(result.rerank_elapsed_ms, 2),
                        "hits": [
                            {
                                "chunk_id": hit.entity_id,
                                "score": round(float(hit.score), 6),
                                "section_path": hit.metadata.get("section_path"),
                                "document_id": hit.metadata.get("document_id"),
                            }
                            for hit in result.hits
                        ],
                        "metrics": metrics,
                        "refusal_evidence_pass": calculate_refusal_evidence_result(
                            source_sections=source_sections,
                            expected_sections=case.expected_source_sections,
                            expected_refusal=case.expected_refusal,
                        ),
                        "error": None,
                    }
                )
            except Exception as error:
                report_items.append(
                    {
                        "case_id": case.case_id,
                        "query": case.query,
                        "focus": case.focus,
                        "mode": mode.value,
                        "expected_source_sections": list(case.expected_source_sections),
                        "expected_refusal": case.expected_refusal,
                        "retrieval_elapsed_ms": round((perf_counter() - started_at) * 1000, 2),
                        "reranked": False,
                        "rerank_elapsed_ms": 0.0,
                        "hits": [],
                        "metrics": calculate_section_metrics([], case.expected_source_sections, case.top_k),
                        "refusal_evidence_pass": False if case.expected_refusal else None,
                        # 只保留异常类型，避免报告意外包含查询、连接串或底层响应内容。
                        "error": type(error).__name__,
                    }
                )

    report = {
        "schema_version": 1,
        "cases_file": str(args.cases_file),
        "item_count": len(report_items),
        "experiment_snapshot": build_knowledge_experiment_snapshot(
            cases_file=args.cases_file,
            definition=definition,
        ),
        "items": report_items,
    }
    report["summary"] = build_knowledge_evaluation_summary(report_items)
    rendered_report = json.dumps(report, ensure_ascii=False, indent=2)
    print(rendered_report)

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered_report + "\n", encoding="utf-8")
        print(f"评测报告已写入：{args.output}")
    markdown_output = args.markdown_output or (
        args.output.with_suffix(".md") if args.output else None
    )
    if markdown_output:
        markdown_output.parent.mkdir(parents=True, exist_ok=True)
        markdown_output.write_text(
            render_knowledge_markdown_report(report),
            encoding="utf-8",
        )
        print(f"Markdown 评测报告已写入：{markdown_output}")


if __name__ == "__main__":
    asyncio.run(main())
