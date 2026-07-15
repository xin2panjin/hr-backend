"""制度切片策略对比脚本的纯配置测试。"""

import json

import pytest

from scripts.evaluate_recruiting_policy_chunking_strategies import (
    STRATEGIES,
    build_processing_config,
    load_existing_comparison,
)


@pytest.mark.parametrize("strategy", STRATEGIES)
def test_build_processing_config_supports_each_experiment_strategy(strategy):
    config = build_processing_config(
        strategy=strategy,
        max_characters=500,
        overlap_characters=80,
    )

    assert config.chunking.strategy.value == strategy
    assert config.chunking.max_characters == 500
    assert config.chunking.overlap_characters == 80


def test_build_processing_config_validates_lengths_before_rebuild():
    with pytest.raises(ValueError, match="overlap_characters"):
        build_processing_config(
            strategy="langchain_recursive",
            max_characters=100,
            overlap_characters=100,
        )


def test_load_existing_comparison_only_keeps_same_document_strategy_items(tmp_path):
    comparison_path = tmp_path / "comparison.json"
    comparison_path.write_text(
        json.dumps(
            {
                "document_id": "document-1",
                "items": [
                    {"strategy": "structured_builtin", "task_id": "task-1"},
                    {"strategy": "unsupported", "task_id": "task-2"},
                ],
            }
        ),
        encoding="utf-8",
    )

    items = load_existing_comparison(comparison_path, document_id="document-1")

    assert items == {"structured_builtin": {"strategy": "structured_builtin", "task_id": "task-1"}}
    assert load_existing_comparison(comparison_path, document_id="document-2") == {}
