"""人才检索离线评测的样本、指标与 Markdown 报告能力。"""

import json
import hashlib
from dataclasses import dataclass
from datetime import datetime
from math import log2
from pathlib import Path
from statistics import mean
from typing import Any


DEFAULT_EVALUATION_CASES_PATH = Path(__file__).resolve().parents[1] / "docs" / "人才库检索评测查询集.json"


@dataclass(frozen=True, slots=True)
class TalentSearchEvaluationCase:
    """一条带人工相关性标注的检索评测样本。"""

    case_id: str
    query: str
    focus: str
    top_k: int = 10
    status: str | None = None
    relevant_candidate_ids: tuple[str, ...] = ()
    expect_empty_result: bool = False


def load_evaluation_cases(path: Path = DEFAULT_EVALUATION_CASES_PATH) -> list[TalentSearchEvaluationCase]:
    """加载并校验评测集，确保相关性标注可重复使用。"""

    raw_cases = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw_cases, list) or not raw_cases:
        raise ValueError("评测查询集必须是非空 JSON 数组")
    cases, case_ids = [], set()
    for index, raw_case in enumerate(raw_cases, start=1):
        if not isinstance(raw_case, dict):
            raise ValueError(f"第 {index} 条评测样本必须是对象")
        case_id = str(raw_case.get("case_id", "")).strip()
        query = str(raw_case.get("query", "")).strip()
        focus = str(raw_case.get("focus", "")).strip()
        top_k, status = raw_case.get("top_k", 10), raw_case.get("status")
        relevant_ids = raw_case.get("relevant_candidate_ids", [])
        expect_empty = raw_case.get("expect_empty_result", False)
        if not case_id or not query or not focus:
            raise ValueError(f"第 {index} 条评测样本缺少 case_id、query 或 focus")
        if case_id in case_ids:
            raise ValueError(f"评测样本 case_id 重复：{case_id}")
        if not isinstance(top_k, int) or not 1 <= top_k <= 50:
            raise ValueError(f"评测样本 {case_id} 的 top_k 必须在 1 到 50 之间")
        if status is not None and not isinstance(status, str):
            raise ValueError(f"评测样本 {case_id} 的 status 必须是字符串")
        if not isinstance(relevant_ids, list) or any(not isinstance(item, str) or not item.strip() for item in relevant_ids):
            raise ValueError(f"评测样本 {case_id} 的 relevant_candidate_ids 必须是字符串数组")
        if len(set(relevant_ids)) != len(relevant_ids):
            raise ValueError(f"评测样本 {case_id} 的 relevant_candidate_ids 不能重复")
        if not isinstance(expect_empty, bool):
            raise ValueError(f"评测样本 {case_id} 的 expect_empty_result 必须是布尔值")
        case_ids.add(case_id)
        cases.append(TalentSearchEvaluationCase(case_id, query, focus, top_k, status, tuple(relevant_ids), expect_empty))
    return cases


def calculate_ranking_metrics(candidate_ids: list[str], relevant_ids: tuple[str, ...], top_k: int) -> dict[str, float | int | None]:
    """计算二元相关性下的 Recall@K、Precision@K、MRR 与 nDCG@K。"""

    if not relevant_ids:
        return {"recall_at_k": None, "precision_at_k": None, "mrr": None, "ndcg_at_k": None, "relevant_count": 0}
    relevant, ranking = set(relevant_ids), candidate_ids[:top_k]
    hits = [index for index, candidate_id in enumerate(ranking, start=1) if candidate_id in relevant]
    recall = len({ranking[index - 1] for index in hits}) / len(relevant)
    precision = len({ranking[index - 1] for index in hits}) / top_k
    mrr = 1 / hits[0] if hits else 0.0
    dcg = sum(1 / log2(index + 1) for index in hits)
    ideal_dcg = sum(1 / log2(index + 1) for index in range(1, min(len(relevant), top_k) + 1))
    return {"recall_at_k": recall, "precision_at_k": precision, "mrr": mrr, "ndcg_at_k": dcg / ideal_dcg if ideal_dcg else 0.0, "relevant_count": len(relevant)}


def build_evaluation_summary(items: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """按模式汇总召回、重排、最终返回三阶段指标与空结果准确率。"""

    summary: dict[str, dict[str, Any]] = {}
    for mode in ("dense", "sparse", "hybrid"):
        mode_items = [item for item in items if item["mode"] == mode and item["error"] is None]
        labeled = [item for item in mode_items if item["metrics"]["retrieval"]["recall_at_k"] is not None]
        expected_empty = [item for item in mode_items if item["expect_empty_result"]]
        def avg(path: str, field: str) -> float | None:
            values = [item[path][field] for item in mode_items if item[path][field] is not None]
            return round(mean(values), 4) if values else None
        def metric_avg(stage: str, field: str) -> float | None:
            values = [item["metrics"][stage][field] for item in labeled]
            return round(mean(values), 4) if values else None
        def empty_accuracy(stage: str) -> dict[str, float | int]:
            passed = sum(not item[stage]["candidate_ids"] for item in expected_empty)
            return {"case_count": len(expected_empty), "pass_count": passed, "accuracy": round(passed / len(expected_empty), 4) if expected_empty else 0.0}
        metric_fields = ("recall_at_k", "precision_at_k", "mrr", "ndcg_at_k")
        summary[mode] = {
            "successful_run_count": len(mode_items),
            "labeled_case_count": len(labeled),
            "retrieval": {"avg_latency_ms": avg("retrieval", "latency_ms"), **{field: metric_avg("retrieval", field) for field in metric_fields}, "empty_result": empty_accuracy("retrieval")},
            "rerank": {"avg_latency_ms": avg("rerank", "elapsed_ms"), **{field: metric_avg("rerank", field) for field in metric_fields}, "empty_result": empty_accuracy("rerank")},
            "final": {"avg_finalization_latency_ms": avg("final", "finalization_elapsed_ms"), "avg_total_latency_ms": avg("final", "total_elapsed_ms"), **{field: metric_avg("final", field) for field in metric_fields}, "empty_result": empty_accuracy("final")},
        }
    return summary


def render_markdown_report(report: dict[str, Any]) -> str:
    """渲染可读的评测摘要；完整候选人 ID 与分数保留在 JSON 报告。"""

    def value(number: float | None) -> str:
        return "-" if number is None else f"{number:.4f}"
    snapshot = report.get("experiment_snapshot", {})
    lines = ["# 人才库检索评测报告", "", f"- 评测集：`{report['cases_file']}`", f"- 执行项：{report['item_count']}", "", "## 实验快照", "", f"- 生成时间：{snapshot.get('generated_at', '-')}", f"- 评测集 SHA-256：`{snapshot.get('cases_file_sha256', '-')}`", f"- Embedding：`{snapshot.get('embedding_model', '-')}`", f"- Reranker：`{snapshot.get('rerank_model', '-')}`（启用：{snapshot.get('rerank_enabled', '-')}）", f"- Milvus：`{snapshot.get('milvus_collection', '-')}` / `{snapshot.get('milvus_database', '-')}`，画像数：{snapshot.get('profile_snapshot', {}).get('profile_count', '-')}", "", "## 汇总", "", "| 模式 | 标注样本 | 召回 R/P/MRR/nDCG | 重排 R/P/MRR/nDCG | 最终 R/P/MRR/nDCG | 召回 ms | 重排 ms | 最终处理 ms | 总耗时 ms |", "| --- | ---: | --- | --- | --- | ---: | ---: | ---: | ---: |"]
    for mode, item in report["summary"].items():
        retrieval, rerank, final = item["retrieval"], item["rerank"], item["final"]
        metric = lambda stage: " / ".join(value(stage[field]) for field in ("recall_at_k", "precision_at_k", "mrr", "ndcg_at_k"))
        lines.append(f"| {mode} | {item['labeled_case_count']} | {metric(retrieval)} | {metric(rerank)} | {metric(final)} | {value(retrieval['avg_latency_ms'])} | {value(rerank['avg_latency_ms'])} | {value(final['avg_finalization_latency_ms'])} | {value(final['avg_total_latency_ms'])} |")
    lines.extend(["", "## 空结果准确率", "", "| 模式 | 召回阶段 | 重排阶段 | 最终返回 |", "| --- | --- | --- | --- |"])
    for mode, item in report["summary"].items():
        render_empty = lambda stage: f"{stage['empty_result']['pass_count']} / {stage['empty_result']['case_count']} ({stage['empty_result']['accuracy']:.2%})"
        lines.append(f"| {mode} | {render_empty(item['retrieval'])} | {render_empty(item['rerank'])} | {render_empty(item['final'])} |")
    lines.extend(["", "## 样本明细", "", "| 样本 | 模式 | 召回命中 | 重排命中 | 最终命中 | 召回 Recall@K | 重排 Recall@K | 最终 Recall@K |", "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |"])
    for item in report["items"]:
        retrieval, rerank, final = item["retrieval"], item["rerank"], item["final"]
        metrics = item["metrics"]
        lines.append(f"| {item['case_id']} | {item['mode']} | {len(retrieval['candidate_ids'])} | {len(rerank['candidate_ids'])} | {len(final['candidate_ids'])} | {value(metrics['retrieval']['recall_at_k'])} | {value(metrics['rerank']['recall_at_k'])} | {value(metrics['final']['recall_at_k'])} |")
    lines.extend(["", "说明：R=Recall@K，P=Precision@K。排序指标只统计具备 `relevant_candidate_ids` 标注的样本；空结果准确率只统计 `expect_empty_result=true` 的样本。", ""])
    return "\n".join(lines)


def build_experiment_snapshot(*, cases_file: Path, settings: Any, profile_snapshot: dict[str, int]) -> dict[str, Any]:
    """记录不含密钥的运行配置，保证评测结果可复现、可横向比较。"""

    return {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "cases_file_sha256": hashlib.sha256(cases_file.read_bytes()).hexdigest(),
        "embedding_model": settings.EMBEDDING_MODEL,
        "milvus_database": settings.MILVUS_DATABASE,
        "milvus_collection": settings.MILVUS_CANDIDATE_COLLECTION,
        "milvus_vector_dim": settings.MILVUS_CANDIDATE_VECTOR_DIM,
        "retrieval": {"dense_recall_k": settings.TALENT_SEARCH_DENSE_RECALL_K, "sparse_recall_k": settings.TALENT_SEARCH_SPARSE_RECALL_K, "hybrid_limit": settings.TALENT_SEARCH_HYBRID_LIMIT},
        "rerank_enabled": settings.TALENT_SEARCH_RERANK_ENABLED,
        "rerank_provider": settings.TALENT_SEARCH_RERANK_PROVIDER,
        "rerank_model": settings.TALENT_SEARCH_RERANK_MODEL,
        "rerank_max_profile_chars": settings.TALENT_SEARCH_RERANK_MAX_PROFILE_CHARS,
        "profile_snapshot": profile_snapshot,
    }
