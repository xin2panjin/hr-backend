from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, BackgroundTasks, Query

from core.cache import HRCache
from dependencies import get_session_instance, get_current_user, get_cache_instance
from models import AsyncSession
from models.user import UserModel
from repository.candidate_repo import CandidateRepo
from schemas.candidate_schema import ResumeUploadRespSchema, ResumePaseSchema, ResumeParseTaskRespSchema, ResumeParseTaskInfoRespSchema, CandidateCreateSchema, CandidateStatusUpdateSchema, CandidateAIScoreRespSchema
from schemas import ResponseSchema
from tasks.candidate_tasks import run_candidate_agent_by_id
from tasks.candidate_index_tasks import sync_candidate_index_batch_task
from tasks.resume_tasks import ocr_parse_resume_task
from schemas.candidate_schema import CandidateListSchema
from models.candidate import CandidateStatusEnum
from repository.candidate_repo import CandidateAIScoreRepo
from services.candidate_service import CandidateService
from services.resume_service import ResumeService

# uv add aiofiles

# uv add loguru

# PaddleOCR私有化部署教程：https://www.paddleocr.ai/latest/index.html


router = APIRouter(prefix="/candidate", tags=["candidate"])

# 上传简历
@router.post("/resume/upload", summary="上传简历", response_model=ResumeUploadRespSchema)
async def resume_upload(
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_session_instance),
    current_user: UserModel = Depends(get_current_user),
):
    async with session.begin():
        resume_service = ResumeService(session=session)
        resume = await resume_service.upload_resume(file, current_user)
    return {"resume": resume}

# 1. 发起了一个简历识别的请求，创建一个后台任务，把task_id返回给前端
# 2. 前端就可以通过task_id来获取这个任务的执行结果，当执行结果为success时，那么就返回解析后的数据
@router.post("/resume/parse", summary="简历解析", response_model=ResumeParseTaskRespSchema)
async def parse_resume(
    resume_data: ResumePaseSchema,
    background_tasks: BackgroundTasks,
    _: UserModel = Depends(get_current_user),
):
    # 创建一个识别简历的后台任务
    resume_service = ResumeService()
    task_id = resume_service.create_parse_task_id()
    background_tasks.add_task(ocr_parse_resume_task, resume_id=resume_data.resume_id, task_id=task_id)
    return {"task_id": task_id}

@router.get("/resume/parse/{task_id}", summary="获取任务状态", response_model=ResumeParseTaskInfoRespSchema)
async def get_task_status(
    task_id: str,
    cache: HRCache = Depends(get_cache_instance),
    _: UserModel = Depends(get_current_user)
):
    resume_service = ResumeService(cache=cache)
    task_info = await resume_service.get_parse_task_info(task_id)
    return task_info.model_dump()

@router.post("/create", summary="创建候选人", response_model=ResponseSchema)
async def create_candidate(
    candidate_data: CandidateCreateSchema,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_session_instance),
    current_user: UserModel = Depends(get_current_user),
):
    async with session.begin():
        candidate_service = CandidateService(session=session)
        candidate_id = await candidate_service.create_candidate(candidate_data, current_user)

    # 创建候选人后会写入 candidate_index_outbox。
    # 这里在事务提交后异步同步到 Milvus，避免请求阻塞在向量生成和 Milvus 写入上。
    background_tasks.add_task(
        sync_candidate_index_batch_task,
        limit=20,
    )

    background_tasks.add_task(
        run_candidate_agent_by_id,
        candidate_id=candidate_id,
    )

    return ResponseSchema()

@router.get("/list", summary="获取候选人列表", response_model=CandidateListSchema)
async def get_candidate_list(
    page: int = Query(1, description="页码"),
    size: int = Query(10, description="每页的数量"),
    position_id: str|None = Query(None, description="职位的ID"),
    status: CandidateStatusEnum|None = Query(None, description="候选人状态"),
    session: AsyncSession = Depends(get_session_instance),
    current_user: UserModel = Depends(get_current_user),
):
    async with session.begin():
        candidate_repo = CandidateRepo(session=session)
        candidates = await candidate_repo.get_list(
            current_user=current_user,
            position_id=position_id,
            status=status,
            page=page,
            size=size,
        )
        return {"candidates": candidates}

@router.patch("/{candidate_id}/status", summary="更新候选人状态", response_model=ResponseSchema)
async def update_candidate_status(
    candidate_id: str,
    status_data: CandidateStatusUpdateSchema,
    session: AsyncSession = Depends(get_session_instance),
    current_user: UserModel = Depends(get_current_user),
):
    async with session.begin():
        candidate_service = CandidateService(session=session)
        await candidate_service.update_candidate_status(candidate_id, status_data, current_user)
        return ResponseSchema()

@router.get("/ai-score/{candidate_id}", summary="获取候选人AI得分", response_model=CandidateAIScoreRespSchema)
async def get_candidate_ai_score(
    candidate_id: str,
    session: AsyncSession = Depends(get_session_instance),
    _: UserModel = Depends(get_current_user),
):
    async with session.begin():
        score_repo = CandidateAIScoreRepo(session)
        ai_score = await score_repo.get_by_candidate_id(candidate_id)
        if not ai_score:
            raise HTTPException(status_code=400, detail="候选人的AI评分不存在！")
        return {"ai_score": ai_score}
