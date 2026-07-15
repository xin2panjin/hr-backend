"""制度知识库索引的 FastAPI 后台任务入口。"""

from loguru import logger

from knowledge.recruiting_policy import build_recruiting_policy_knowledge_base_definition
from models import AsyncSessionFactory
from services.knowledge_index_service import KnowledgeIndexService


async def run_recruiting_policy_index_task(task_id: str) -> None:
    """在独立会话中执行上传、重建或归档触发的索引任务。"""

    try:
        async with AsyncSessionFactory() as session:
            async with session.begin():
                result = await KnowledgeIndexService(
                    session,
                    knowledge_base_definition=build_recruiting_policy_knowledge_base_definition(),
                ).run_task(task_id)
        logger.info(
            "制度索引任务完成 task_id={} succeeded={} chunk_count={} error_type={}",
            task_id,
            result.succeeded,
            result.chunk_count,
            result.error_type,
        )
    except Exception as error:
        logger.exception("制度索引后台任务异常 task_id={} error_type={}", task_id, type(error).__name__)
