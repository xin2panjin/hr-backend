import os.path

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from loguru import logger

from core.ocr import PaddleOcr
from dependencies import get_session_instance
from models import AsyncSession
from repository.candidate_repo import CandidateRepo
from repository.position_repo import PositionRepo
from repository.user_repo import UserRepo
from schemas.candidate_schema import CandidateSchema
from schemas.position_schema import PositionSchema
from schemas.user_schema import UserSchema
from settings import settings
from tasks.candidate_tasks import run_candidate_agent

router = APIRouter(prefix="/dev", tags=["dev"])


@router.get("/resume/ocr/test")
async def resume_ocr_test():
    file_path = os.path.join(settings.RESUME_DIR, "635c85d6-ba0b-4ffc-b7cb-24817557de11.pdf")
    paddle_ocr = PaddleOcr()
    job_id = await paddle_ocr.create_job(file_path)
    jsonl_url = await paddle_ocr.poll_for_state(job_id)
    contents = await paddle_ocr.fetch_parsed_contents(jsonl_url)
    logger.info(contents)
    return "success"


@router.get("/agent/test")
async def agent_test(
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_session_instance),
):
    async with session.begin():
        candidate_repo = CandidateRepo(session=session)
        position_repo = PositionRepo(session=session)
        user_repo = UserRepo(session=session)

        candidate_model = await candidate_repo.get_by_id("k6sEoXwqR7ZWa8oYWr7UUq")
        position_model = await position_repo.get_by_id("YHre5Lq5J8L4UwhJpSxj44")
        interviewer_model = await user_repo.get_by_id("Q3WtCYFcYgyxEvDp7CnUJ6")

        if not candidate_model or not position_model or not interviewer_model:
            raise HTTPException(status_code=404, detail="测试数据不存在")

        background_tasks.add_task(
            run_candidate_agent,
            candidate=CandidateSchema.model_validate(candidate_model),
            position=PositionSchema.model_validate(position_model),
            interviewer=UserSchema.model_validate(interviewer_model),
        )
        return {"result": "success"}
