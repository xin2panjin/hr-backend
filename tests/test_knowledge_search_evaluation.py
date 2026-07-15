"""制度知识库离线检索评测能力测试。"""

import json

import pytest

from rag.knowledge_search_evaluation import (
    calculate_refusal_evidence_result,
    calculate_section_metrics,
    load_knowledge_evaluation_cases,
    render_knowledge_markdown_report,
    section_matches,
)


def test_load_knowledge_evaluation_cases_loads_the_seed_dataset():
    cases = load_knowledge_evaluation_cases()

    assert len(cases) >= 50
    assert len({case.case_id for case in cases}) == len(cases)
    assert sum(case.expected_refusal for case in cases) >= 4


def test_load_knowledge_evaluation_cases_rejects_ungrounded_non_refusal_case(tmp_path):
    cases_path = tmp_path / "invalid.json"
    cases_path.write_text(
        json.dumps(
            [{"case_id": "invalid", "query": "问题", "focus": "测试", "expected_facts": ["事实"]}],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="expected_source_sections"):
        load_knowledge_evaluation_cases(cases_path)


def test_section_metrics_accept_document_title_prefix_and_ranking():
    expected = ("第四章 休假管理 > 4.1 年休假规则",)
    metrics = calculate_section_metrics(
        [
            "星澜智能科技有限公司人力资源管理制度（试行） > 第四章 休假管理 > 4.1 年休假规则",
            "第五章 薪酬与福利 > 5.1 薪酬结构",
        ],
        expected,
        top_k=2,
    )

    assert metrics["recall_at_k"] == 1.0
    assert metrics["mrr"] == 1.0
    assert metrics["top1_citation_accuracy"] == 1.0
    assert section_matches("第四章 休假管理 > 4.1 年休假规则", expected[0])


def test_refusal_evidence_distinguishes_explicit_and_absent_evidence():
    assert calculate_refusal_evidence_result(
        source_sections=["第五章 薪酬与福利 > 5.3 补充福利"],
        expected_sections=("第五章 薪酬与福利 > 5.3 补充福利",),
        expected_refusal=True,
    ) is True
    assert calculate_refusal_evidence_result(
        source_sections=[], expected_sections=(), expected_refusal=True
    ) is True
    assert calculate_refusal_evidence_result(
        source_sections=["第四章 休假管理"], expected_sections=(), expected_refusal=True
    ) is False


def test_markdown_report_marks_refusal_as_evidence_proxy():
    output = render_knowledge_markdown_report(
        {
            "cases_file": "cases.json",
            "item_count": 3,
            "experiment_snapshot": {"knowledge_base_key": "recruiting_policy", "collection_name": "chunks"},
            "summary": {
                mode: {
                    "grounded_case_count": 1,
                    "avg_recall_at_k": 1.0,
                    "avg_mrr": 1.0,
                    "avg_ndcg_at_k": 1.0,
                    "citation_accuracy": 1.0,
                    "avg_retrieval_latency_ms": 12.0,
                    "refusal_evidence": {"pass_count": 1, "case_count": 1, "accuracy": 1.0},
                }
                for mode in ("dense", "sparse", "hybrid")
            },
        }
    )

    assert "拒答证据为检索代理指标" in output
