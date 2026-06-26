import os

from loguru import logger

from agents.resume import extract_candidate_info
from core.cache import TaskInfoSchema
from core.ocr import PaddleOcr, QwenOcr
from dependencies import HRCache, get_cache_instance
from models import AsyncSessionFactory
from repository.candidate_repo import ResumeModel, ResumeRepo
from schemas.agent_schema import AgentCandidateSchema
from settings import settings


async def ocr_parse_resume_task(
    resume_id: str,
    task_id: str,
):
    async with AsyncSessionFactory() as session:
        async with session.begin():
            resume_repo = ResumeRepo(session=session)
            resume: ResumeModel = await resume_repo.get_by_id(resume_id)

    file_path = os.path.join(settings.RESUME_DIR, resume.file_path)
    cache: HRCache = get_cache_instance()
    await cache.set_task_info(TaskInfoSchema(task_id=task_id, status="pending"))

    try:
        try:
            paddle_ocr = PaddleOcr()
            job_id = await paddle_ocr.create_job(file_path)
            jsonl_url = await paddle_ocr.poll_for_state(job_id)
            contents = await paddle_ocr.fetch_parsed_contents(jsonl_url)
            content = "\n\n".join(contents)
        except Exception as e:
            logger.error(f"PaddleOCR识别失败：{e}")
            qwen_ocr = QwenOcr()
            content = await qwen_ocr.extract_info_from_resume(file_path)

        candidate_info: AgentCandidateSchema = await extract_candidate_info(content)
        await cache.set_task_info(TaskInfoSchema(task_id=task_id, status="done", result=candidate_info))
    except Exception as e:
        logger.error(e)
        await cache.set_task_info(TaskInfoSchema(task_id=task_id, status="failed", error=str(e)))
