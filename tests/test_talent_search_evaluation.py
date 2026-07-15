import json

import pytest

from rag.talent_search_evaluation import (
    build_evaluation_summary,
    calculate_ranking_metrics,
    load_evaluation_cases,
    render_markdown_report,
)


def test_default_evaluation_cases_cover_core_retrieval_scenarios():
    """固定查询集至少覆盖精确词、语义、融合、过滤和空结果。"""

    cases = load_evaluation_cases()
    case_ids = {case.case_id for case in cases}

    assert {
        "exact_tech_skills",
        "semantic_rag_experience",
        "backend_risk_experience",
        "status_filter",
        "empty_result",
    }.issubset(case_ids)
    assert len(case_ids) == len(cases)


def test_evaluation_cases_reject_duplicate_case_id(tmp_path):
    """重复样本 ID 会使对比报告不可读，加载时必须拒绝。"""

    cases_file = tmp_path / "cases.json"
    cases_file.write_text(
        json.dumps(
            [
                {"case_id": "same", "query": "Python", "focus": "精确词"},
                {"case_id": "same", "query": "RAG", "focus": "语义"},
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="case_id 重复"):
        load_evaluation_cases(cases_file)


def test_ranking_metrics_calculates_recall_mrr_and_ndcg():
    """指标应基于人工标注的相关候选人，而不是模型分数。"""

    metrics = calculate_ranking_metrics(
        ["irrelevant", "candidate-2", "candidate-1"],
        ("candidate-1", "candidate-2"),
        top_k=2,
    )

    assert metrics["recall_at_k"] == 0.5
    assert metrics["precision_at_k"] == 0.5
    assert metrics["mrr"] == 0.5
    assert metrics["ndcg_at_k"] == pytest.approx(0.38685, abs=0.00001)


def test_markdown_report_renders_summary_and_detail_table():
    """Markdown 报告应同时展示聚合指标和样本级结果。"""

    item = {
        "case_id": "case-1", "mode": "dense", "error": None,
        "expect_empty_result": False,
        "retrieval": {"candidate_ids": ["candidate-1"], "latency_ms": 10.0},
        "rerank": {"candidate_ids": ["candidate-1"], "elapsed_ms": 5.0},
        "final": {"candidate_ids": ["candidate-1"], "finalization_elapsed_ms": 1.0, "total_elapsed_ms": 16.0},
        "metrics": {
            stage: {"recall_at_k": 1.0, "precision_at_k": 1.0, "mrr": 1.0, "ndcg_at_k": 1.0}
            for stage in ("retrieval", "rerank", "final")
        },
    }
    report = {"cases_file": "cases.json", "item_count": 1, "items": [item], "experiment_snapshot": {}, "summary": build_evaluation_summary([item])}
    rendered = render_markdown_report(report)

    assert "# 人才库检索评测报告" in rendered
    assert "## 样本明细" in rendered
    assert "case-1" in rendered
