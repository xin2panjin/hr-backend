"""制度知识库离线检索评测的样本、指标与报告能力。"""

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from math import log2
from pathlib import Path
from statistics import mean
from typing import Any, Iterable


DEFAULT_KNOWLEDGE_EVALUATION_CASES_PATH = (
    Path(__file__).resolve().parents[1]
    / "docs/knowledge_samples/recruiting_policy/企业制度知识库评测集_V1.0.json"
)


@dataclass(frozen=True, slots=True)
class KnowledgeEvaluationCase:
    """一条带章节和关键事实标注的制度知识库评测样本。"""

    case_id: str
    query: str
    focus: str
    top_k: int
    expected_source_sections: tuple[str, ...]
    expected_facts: tuple[str, ...]
    expected_refusal: bool = False


def load_knowledge_evaluation_cases(
    path: Path = DEFAULT_KNOWLEDGE_EVALUATION_CASES_PATH,
) -> list[KnowledgeEvaluationCase]:
    """加载并校验知识库评测集，避免标注错误污染对比结果。"""

    raw_cases = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw_cases, list) or not raw_cases:
        raise ValueError("知识库评测集必须是非空 JSON 数组")

    cases: list[KnowledgeEvaluationCase] = []
    case_ids: set[str] = set()
    for index, raw_case in enumerate(raw_cases, start=1):
        if not isinstance(raw_case, dict):
            raise ValueError(f"第 {index} 条知识库评测样本必须是对象")
        case_id = _required_text(raw_case.get("case_id"), "case_id", index)
        query = _required_text(raw_case.get("query"), "query", index)
        focus = _required_text(raw_case.get("focus"), "focus", index)
        top_k = raw_case.get("top_k", 5)
        source_sections = _string_list(raw_case.get("expected_source_sections", []), "expected_source_sections", index)
        expected_facts = _string_list(raw_case.get("expected_facts", []), "expected_facts", index)
        expected_refusal = raw_case.get("expected_refusal", False)
        if case_id in case_ids:
            raise ValueError(f"知识库评测样本 case_id 重复：{case_id}")
        if not isinstance(top_k, int) or not 1 <= top_k <= 20:
            raise ValueError(f"评测样本 {case_id} 的 top_k 必须在 1 到 20 之间")
        if not expected_facts:
            raise ValueError(f"评测样本 {case_id} 缺少 expected_facts")
        if not isinstance(expected_refusal, bool):
            raise ValueError(f"评测样本 {case_id} 的 expected_refusal 必须是布尔值")
        if not source_sections and not expected_refusal:
            raise ValueError(f"评测样本 {case_id} 缺少 expected_source_sections")
        case_ids.add(case_id)
        cases.append(
            KnowledgeEvaluationCase(
                case_id=case_id,
                query=query,
                focus=focus,
                top_k=top_k,
                expected_source_sections=tuple(source_sections),
                expected_facts=tuple(expected_facts),
                expected_refusal=expected_refusal,
            )
        )
    return cases


def calculate_section_metrics(
    source_sections: Iterable[str | None],
    expected_sections: tuple[str, ...],
    top_k: int,
) -> dict[str, float | int | None]:
    """按预期章节计算 Recall@K、MRR、nDCG 与首条引用准确率。"""

    if not expected_sections:
        return {
            "recall_at_k": None,
            "mrr": None,
            "ndcg_at_k": None,
            "top1_citation_accuracy": None,
            "expected_section_count": 0,
        }
    ranked_sections = list(source_sections)[:top_k]
    matched_expected: set[str] = set()
    hit_positions: list[int] = []
    for position, source_section in enumerate(ranked_sections, start=1):
        for expected_section in expected_sections:
            if expected_section in matched_expected:
                continue
            if section_matches(source_section, expected_section):
                matched_expected.add(expected_section)
                hit_positions.append(position)
                break
    recall = len(matched_expected) / len(expected_sections)
    dcg = sum(1 / log2(position + 1) for position in hit_positions)
    ideal_dcg = sum(
        1 / log2(position + 1)
        for position in range(1, min(len(expected_sections), top_k) + 1)
    )
    return {
        "recall_at_k": recall,
        "mrr": 1 / hit_positions[0] if hit_positions else 0.0,
        "ndcg_at_k": dcg / ideal_dcg if ideal_dcg else 0.0,
        "top1_citation_accuracy": float(
            bool(ranked_sections)
            and any(section_matches(ranked_sections[0], item) for item in expected_sections)
        ),
        "expected_section_count": len(expected_sections),
    }


def calculate_refusal_evidence_result(
    *,
    source_sections: Iterable[str | None],
    expected_sections: tuple[str, ...],
    expected_refusal: bool,
) -> bool | None:
    """计算拒答证据代理指标，不把检索结果误称为 LLM 拒答结果。

    对“制度中明确说明未覆盖”的问题，应检索到标注章节作为拒答依据；
    对没有任何标注章节的问题，应避免召回看似确定的制度条款。
    """

    if not expected_refusal:
        return None
    ranked_sections = list(source_sections)
    if expected_sections:
        return any(
            section_matches(source_section, expected_section)
            for source_section in ranked_sections
            for expected_section in expected_sections
        )
    return not ranked_sections


def build_knowledge_evaluation_summary(items: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """按检索模式汇总章节召回、来源引用和拒答证据代理指标。"""

    summary: dict[str, dict[str, Any]] = {}
    for mode in ("dense", "sparse", "hybrid"):
        mode_items = [item for item in items if item["mode"] == mode and item["error"] is None]
        grounded_items = [item for item in mode_items if not item["expected_refusal"]]
        refusal_items = [item for item in mode_items if item["expected_refusal"]]

        def average(field: str) -> float | None:
            values = [item["metrics"][field] for item in grounded_items]
            return round(mean(values), 4) if values else None

        refusal_pass_count = sum(
            bool(item["refusal_evidence_pass"])
            for item in refusal_items
        )
        summary[mode] = {
            "successful_run_count": len(mode_items),
            "grounded_case_count": len(grounded_items),
            "avg_recall_at_k": average("recall_at_k"),
            "avg_mrr": average("mrr"),
            "avg_ndcg_at_k": average("ndcg_at_k"),
            "citation_accuracy": average("top1_citation_accuracy"),
            "avg_retrieval_latency_ms": round(
                mean(item["retrieval_elapsed_ms"] for item in mode_items), 2
            ) if mode_items else None,
            "refusal_evidence": {
                "case_count": len(refusal_items),
                "pass_count": refusal_pass_count,
                "accuracy": round(refusal_pass_count / len(refusal_items), 4) if refusal_items else 0.0,
            },
        }
    return summary


def render_knowledge_markdown_report(report: dict[str, Any]) -> str:
    """将知识库检索评测报告渲染为便于比较的 Markdown。"""

    def value(number: float | None) -> str:
        return "-" if number is None else f"{number:.4f}"

    lines = [
        "# 制度知识库检索评测报告",
        "",
        f"- 评测集：`{report['cases_file']}`",
        f"- 执行项：{report['item_count']}",
        f"- 知识库：`{report['experiment_snapshot']['knowledge_base_key']}`",
        f"- Collection：`{report['experiment_snapshot']['collection_name']}`",
        "",
        "## 汇总",
        "",
        "| 模式 | 有依据样本 | Recall@K | MRR | nDCG@K | 首条引用准确率 | 召回耗时 ms | 拒答证据 |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for mode, item in report["summary"].items():
        refusal = item["refusal_evidence"]
        lines.append(
            f"| {mode} | {item['grounded_case_count']} | {value(item['avg_recall_at_k'])} | "
            f"{value(item['avg_mrr'])} | {value(item['avg_ndcg_at_k'])} | "
            f"{value(item['citation_accuracy'])} | {value(item['avg_retrieval_latency_ms'])} | "
            f"{refusal['pass_count']} / {refusal['case_count']} ({refusal['accuracy']:.2%}) |"
        )
    lines.extend([
        "",
        "说明：首条引用准确率仅统计有正式制度依据的样本；拒答证据为检索代理指标，"
        "不等同于 LLM 最终回复的拒答准确率。",
        "",
    ])
    return "\n".join(lines)


def build_knowledge_experiment_snapshot(*, cases_file: Path, definition) -> dict[str, Any]:
    """记录不含密钥的知识库检索配置，保证实验可比较。"""

    return {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "cases_file_sha256": hashlib.sha256(cases_file.read_bytes()).hexdigest(),
        "knowledge_base_key": definition.key,
        "collection_name": definition.collection_name,
        "schema_version": definition.schema_version,
        "retrieval_config": dict(definition.retrieval_config),
    }


def section_matches(actual_section: str | None, expected_section: str) -> bool:
    """兼容文档标题前缀差异，按完整章节路径而非关键词做匹配。"""

    if not actual_section:
        return False
    actual = _normalize_section(actual_section)
    expected = _normalize_section(expected_section)
    return actual.endswith(expected) or expected.endswith(actual)


def _normalize_section(value: str) -> str:
    return " > ".join(part.strip() for part in value.split(">") if part.strip())


def _required_text(value: Any, field_name: str, index: int) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError(f"第 {index} 条知识库评测样本缺少 {field_name}")
    return normalized


def _string_list(value: Any, field_name: str, index: int) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) or not item.strip() for item in value):
        raise ValueError(f"第 {index} 条知识库评测样本的 {field_name} 必须是字符串数组")
    if len(set(value)) != len(value):
        raise ValueError(f"第 {index} 条知识库评测样本的 {field_name} 不能重复")
    return [item.strip() for item in value]
