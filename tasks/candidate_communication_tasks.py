from loguru import logger

from services.candidate_communication_service import CandidateCommunicationInsightWorker


async def process_candidate_communication_insights_task(limit: int = 10) -> None:
    """请求提交后异步处理洞察 outbox；失败保留为可重试状态。"""

    try:
        count = await CandidateCommunicationInsightWorker().process_pending(limit=limit)
        logger.info(f"候选人沟通洞察后台处理完成，成功处理 {count} 条")
    except Exception as exc:
        logger.exception(f"候选人沟通洞察后台处理失败：{exc}")
