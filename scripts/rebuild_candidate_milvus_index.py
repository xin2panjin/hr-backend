"""候选人 Milvus 索引全量回灌命令。

执行示例：
    uv run python -m scripts.rebuild_candidate_milvus_index
    uv run python -m scripts.rebuild_candidate_milvus_index --dry-run
    uv run python -m scripts.rebuild_candidate_milvus_index --changed-only
"""

import argparse
import asyncio

from services.candidate_index_backfill_service import CandidateIndexBackfillService


def parse_args() -> argparse.Namespace:
    """解析全量回灌命令参数。"""

    parser = argparse.ArgumentParser(description="全量回灌候选人 Milvus 检索索引")
    parser.add_argument(
        "--batch-size",
        type=int,
        default=100,
        help="每批读取和同步的候选人数，默认 100",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只统计会受影响的候选人，不写 PostgreSQL 或 Milvus",
    )
    parser.add_argument(
        "--changed-only",
        action="store_true",
        help="仅处理缺失或画像内容变化的候选人，不强制重建全部向量",
    )
    return parser.parse_args()


async def main() -> None:
    """执行回灌并打印便于人工核对的汇总结果。"""

    args = parse_args()
    result = await CandidateIndexBackfillService().rebuild_all(
        batch_size=args.batch_size,
        force_reindex=not args.changed_only,
        dry_run=args.dry_run,
    )
    print(
        "候选人索引回灌完成："
        f"扫描={result.scanned_candidates}，"
        f"重建画像={result.rebuilt_profiles}，"
        f"未变化={result.unchanged_profiles}，"
        f"候选人不存在={result.missing_candidates}，"
        f"画像失败={result.profile_failures}，"
        f"成功同步事件={result.indexed_events}，"
        f"同步批次失败={result.sync_failures}"
    )


if __name__ == "__main__":
    asyncio.run(main())
