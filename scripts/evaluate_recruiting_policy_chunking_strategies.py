"""依次重建制度文档并比较四种切分策略的检索基线。

执行示例：
    uv run python -m scripts.evaluate_recruiting_policy_chunking_strategies \
      --document-id <制度文档ID> --actor-id <操作用户ID> --apply-index

注意：每次重建会替换该文档在 Milvus 与 PostgreSQL 中的旧切片；最后一次
执行的策略会成为文档当前的生产切片策略。建议仅对测试制度文档运行。
"""

import argparse
import asyncio
import json
import subprocess
import sys
from pathlib import Path

from knowledge.recruiting_policy import build_recruiting_policy_knowledge_base_definition
from models import AsyncSessionFactory
from services.knowledge_document_service import KnowledgeDocumentService
from services.knowledge_index_service import KnowledgeIndexService
from services.knowledge_text_processing import KnowledgeTextProcessingConfig


STRATEGIES = (
    "structured_builtin",
    "fixed_length",
    "custom_character",
    "langchain_recursive",
)
DEFAULT_CUSTOM_SEPARATOR = "。"


def parse_args() -> argparse.Namespace:
    """解析实验对象、执行者和需对比的策略。"""

    parser = argparse.ArgumentParser(description="比较企业制度知识库的四种切分策略")
    parser.add_argument("--document-id", required=True, help="仅可使用测试制度文档 ID")
    parser.add_argument("--actor-id", required=True, help="记录重建操作的现有系统用户 ID")
    parser.add_argument(
        "--strategy",
        action="append",
        choices=STRATEGIES,
        help="仅运行指定策略；默认依次运行全部四种策略",
    )
    parser.add_argument("--max-characters", type=int, default=500)
    parser.add_argument("--overlap-characters", type=int, default=80)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("output/recruiting-policy-chunking-comparison"),
    )
    parser.add_argument(
        "--apply-index",
        action="store_true",
        help="确认依次重建索引；不传该参数时脚本拒绝修改文档索引",
    )
    return parser.parse_args()


def build_processing_config(
    *,
    strategy: str,
    max_characters: int,
    overlap_characters: int,
) -> KnowledgeTextProcessingConfig:
    """为每个实验策略构造可直接写入索引任务的配置快照。"""

    return KnowledgeTextProcessingConfig.from_mapping(
        {
            "chunking": {
                "strategy": strategy,
                "max_characters": max_characters,
                "overlap_characters": overlap_characters,
                "custom_separator": DEFAULT_CUSTOM_SEPARATOR,
            }
        }
    )


async def rebuild_document(
    *,
    document_id: str,
    actor_id: str,
    processing_config: KnowledgeTextProcessingConfig,
) -> str:
    """创建并完成一次可追溯的 REBUILD 任务。"""

    async with AsyncSessionFactory() as session:
        async with session.begin():
            task = await KnowledgeDocumentService(session=session).request_rebuild(
                knowledge_base_key="recruiting_policy",
                document_id=document_id,
                actor_id=actor_id,
                processing_config=processing_config,
            )
        task_id = task.id
    # 实验脚本不能导入 tasks 包：该包会加载候选人 Agent 等无关依赖，
    # 使纯索引实验受模型客户端、代理配置等运行环境影响。
    async with AsyncSessionFactory() as session:
        async with session.begin():
            result = await KnowledgeIndexService(
                session,
                knowledge_base_definition=build_recruiting_policy_knowledge_base_definition(),
            ).run_task(task_id)
    if not result.succeeded:
        raise RuntimeError(
            f"策略重建失败：task_id={task_id} error_type={result.error_type}"
        )
    return task_id


async def run_evaluation(*, output_path: Path) -> dict:
    """复用 D2 命令入口生成单策略检索报告。"""

    command = [
        sys.executable,
        "-m",
        "scripts.evaluate_recruiting_policy_knowledge",
        "--output",
        str(output_path),
    ]
    completed = await asyncio.to_thread(
        subprocess.run,
        command,
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            "D2 评测执行失败："
            f"{completed.stderr[-1000:] or completed.stdout[-1000:]}"
        )
    return json.loads(output_path.read_text(encoding="utf-8"))


def load_existing_comparison(comparison_path: Path, *, document_id: str) -> dict[str, dict]:
    """读取同一文档已完成的单策略结果，支持把长实验拆成多次执行。"""

    if not comparison_path.exists():
        return {}
    existing = json.loads(comparison_path.read_text(encoding="utf-8"))
    if existing.get("document_id") != document_id:
        return {}
    return {
        item["strategy"]: item
        for item in existing.get("items", [])
        if item.get("strategy") in STRATEGIES
    }


async def main() -> None:
    """依次执行重建和评测，输出四策略的可比较摘要。"""

    args = parse_args()
    if not args.apply_index:
        raise ValueError("此操作会重建文档索引；请显式传入 --apply-index")
    strategies = args.strategy or list(STRATEGIES)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    comparison_path = args.output_dir / "comparison.json"
    comparison_items = load_existing_comparison(
        comparison_path,
        document_id=args.document_id,
    )
    for strategy in strategies:
        config = build_processing_config(
            strategy=strategy,
            max_characters=args.max_characters,
            overlap_characters=args.overlap_characters,
        )
        print(f"开始策略实验：{strategy}")
        task_id = await rebuild_document(
            document_id=args.document_id,
            actor_id=args.actor_id,
            processing_config=config,
        )
        report_path = args.output_dir / f"{strategy}.json"
        report = await run_evaluation(output_path=report_path)
        comparison_items[strategy] = {
            "strategy": strategy,
            "task_id": task_id,
            "processing_config": config.to_dict(),
            "report_path": str(report_path),
            "summary": report["summary"],
        }
        print(f"完成策略实验：{strategy}，报告：{report_path}")

    comparison_path.write_text(
        json.dumps(
            {
                "document_id": args.document_id,
                "items": [
                    comparison_items[strategy]
                    for strategy in STRATEGIES
                    if strategy in comparison_items
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"策略对比摘要已写入：{comparison_path}")


if __name__ == "__main__":
    asyncio.run(main())
