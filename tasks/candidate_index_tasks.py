from loguru import logger

from services.candidate_index_sync_service import CandidateIndexSyncService


async def sync_candidate_index_batch(limit: int = 20) -> int:
    """同步一批候选人索引事件到 Milvus。"""

    return await CandidateIndexSyncService().sync_pending_events(limit=limit)

async def sync_candidate_index_batch_task(limit: int = 20) -> None:
    """后台同步候选人索引。

    BackgroundTasks 不关心返回值，所以这里负责记录日志。
    即使同步失败，outbox 事件仍会保留失败状态，后续可以重试。
    """

    try:
        count = await sync_candidate_index_batch(limit=limit)
        logger.info(f"候选人索引后台同步完成，成功处理 {count} 条事件")
    except Exception as exc:
        logger.exception(f"候选人索引后台同步失败：{exc}")
