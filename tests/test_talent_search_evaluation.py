import json

import pytest

from rag.talent_search_evaluation import load_evaluation_cases


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
