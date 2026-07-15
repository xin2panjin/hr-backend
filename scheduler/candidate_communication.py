"""可靠执行候选人沟通洞察 outbox 的常驻调度器。"""

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from loguru import logger

from tasks.candidate_communication_tasks import process_candidate_communication_insights_task


async def start_candidate_communication_scheduler() -> AsyncIOScheduler:
    """每 30 秒扫描一次；事件自身的 available_at 保证五分钟静默窗口。"""

    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        process_candidate_communication_insights_task,
        "interval",
        seconds=30,
        kwargs={"limit": 10},
        max_instances=1,
        coalesce=True,
        id="candidate-communication-insight-outbox",
        replace_existing=True,
    )
    scheduler.start()
    logger.info("候选人沟通洞察调度器已启动")
    return scheduler
