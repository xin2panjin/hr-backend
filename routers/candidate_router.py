import os.path

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, status, BackgroundTasks, Query

from core.cache import HRCache
from dependencies import get_session_instance, get_current_user, get_cache_instance
from models import AsyncSession
from models.user import UserModel
from settings import settings
from uuid import uuid4
import aiofiles
from core.pdf import WordToPdfConverter
from loguru import logger
from repository.candidate_repo import ResumeRepo, CandidateRepo
from schemas.candidate_schema import ResumeUploadRespSchema, ResumePaseSchema, ResumeParseTaskRespSchema, ResumeParseTaskInfoRespSchema, CandidateCreateSchema, CandidateStatusUpdateSchema, CandidateAIScoreRespSchema
from core.ocr import PaddleOcr
from tasks import ocr_parse_resume_task
from schemas import ResponseSchema
from repository.position_repo import PositionRepo
from repository.user_repo import UserRepo
from tasks import run_candidate_agent
from schemas.candidate_schema import CandidateSchema, CandidateListSchema
from schemas.position_schema import PositionSchema
from schemas.user_schema import UserSchema
from models.candidate import CandidateStatusEnum
from repository.interview_repo import InterviewRepo
from models.interview import InterviewResultEnum
from models.interview import InterviewModel
from repository.candidate_repo import CandidateAIScoreRepo

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
    # 1. 校验文件类型
    # 简历：图片、pdf、word
    allowed_mime_types = [
        "application/pdf",
        "application/msword",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "image/jpeg",
        "image/png",
        "image/jpg",
    ]
    if file.content_type not in allowed_mime_types:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="该文件不支持！")

    # 2. 保存文件
    resume_dir = settings.RESUME_DIR
    file_extension = os.path.splitext(file.filename)[-1]
    unique_filename = f"{uuid4()}{file_extension}"
    file_path = os.path.join(resume_dir, unique_filename)
    # with open(file_path, "wb") as f:
    try:
        async with aiofiles.open(file_path, mode="wb") as fp:
            content = await file.read(1024)
            while content:
                await fp.write(content)
                content = await file.read(1024)
    finally:
        await fp.close()

    # 3. 如果是word文档，那么就转化成pdf
    if file_extension == ".doc" or file_extension == ".docx":
        pdf_path = file_path.replace(file_extension, ".pdf")
        converter = WordToPdfConverter(
            word_path=file_path,
            output_pdf_path=pdf_path,
        )
        try:
            await converter.convert()
            file_path = pdf_path
        except Exception as e:
            logger.error(f"Word转PDF失败：{e}")

    # 4. 将简历数据存储到数据库中
    async with session.begin():
        resume_repo = ResumeRepo(session=session)
        resume = await resume_repo.create_resume(file_path=file_path, uploader_id=current_user.id)

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
    task_id = str(uuid4())
    background_tasks.add_task(ocr_parse_resume_task, resume_id=resume_data.resume_id, task_id=task_id)
    return {"task_id": task_id}

@router.get("/resume/parse/{task_id}", summary="获取任务状态", response_model=ResumeParseTaskInfoRespSchema)
async def get_task_status(
    task_id: str,
    cache: HRCache = Depends(get_cache_instance),
    _: UserModel = Depends(get_current_user)
):
    task_info = await cache.get_task_info(task_id)
    return task_info.model_dump()

@router.post("/create", summary="创建候选人", response_model=ResponseSchema)
async def create_candidate(
    candidate_data: CandidateCreateSchema,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_session_instance),
    current_user: UserModel = Depends(get_current_user),
):
    async with session.begin():
        candidate_dict = candidate_data.model_dump()
        candidate_dict['creator_id'] = current_user.id
        candidate_repo = CandidateRepo(session=session)
        candidate = await candidate_repo.create_candidate(candidate_dict)
        candidate_schema = CandidateSchema.model_validate(candidate)
        position_schema = PositionSchema.model_validate(candidate.position)
        interviewer_schema = UserSchema.model_validate(candidate.position.creator)

    background_tasks.add_task(
        run_candidate_agent,
        candidate=candidate_schema,
        position=position_schema,
        interviewer=interviewer_schema,
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
        candidate_repo = CandidateRepo(session)
        interview_repo = InterviewRepo(session)
        candidate = await candidate_repo.get_by_id(candidate_id)
        if not candidate:
            raise HTTPException(status_code=404, detail="候选人不存在")
        # 更改状态，状态只能从前往后流转
        status_flow = [
            CandidateStatusEnum.APPLICATION,
            CandidateStatusEnum.AI_FILTER_FAILED,
            CandidateStatusEnum.AI_FILTER_PASSED,
            CandidateStatusEnum.WAITING_FOR_INTERVIEW,
            CandidateStatusEnum.REFUSED_INTERVIEW,
            CandidateStatusEnum.INTERVIEW_PASSED,
            CandidateStatusEnum.INTERVIEW_REJECTED,
            CandidateStatusEnum.HIRED,
            CandidateStatusEnum.REJECTED,
        ]
        try:
            current_idx = status_flow.index(candidate.status)
            target_idx = status_flow.index(status_data.status)
        except ValueError:
            raise HTTPException(status_code=400, detail="非法的候选人状态")

        if target_idx <= current_idx:
            raise HTTPException(status_code=400, detail="候选人状态只能往后流转")

        if status_data.status == CandidateStatusEnum.WAITING_FOR_INTERVIEW:
            if not status_data.interview_time:
                raise HTTPException(status_code=400, detail="变更为待面试时必须填写面试时间")
            await interview_repo.create_interview(
                dict(
                    scheduled_time=status_data.interview_time,
                    candidate_id=candidate_id,
                    interviewer_id=current_user.id,
                )
            )
        elif status_data.status == CandidateStatusEnum.INTERVIEW_REJECTED:
            if not status_data.rejection_reason:
                raise HTTPException(status_code=400, detail="变更为面试未通过时必须填写未通过原因")
            # 如果面试失败了，一般来讲，应该是之前就已经创建过一个面试记录了
            interview: InterviewModel = await interview_repo.get_by_candidate_id(candidate_id)
            if interview is not None:
                await interview_repo.update_interview(
                    interview_id=interview.id,
                    interview_dict={
                        "feeback": status_data.rejection_reason,
                        "result": InterviewResultEnum.FAILED,
                    }
                )
            else:
                await interview_repo.create_interview(
                    dict(
                        scheduled_time=status_data.interview_time,
                        feedback=status_data.rejection_reason,
                        result=InterviewResultEnum.FAILED,
                        candidate_id=candidate_id,
                        interviewer_id=current_user.id,
                    )
                )

        # 更新候选人状态
        await candidate_repo.update_candidate_status(candidate_id=candidate_id, status=status_data.status)
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

        background_tasks.add_task(
            run_candidate_agent,
            candidate=CandidateSchema.model_validate(candidate_model),
            position=PositionSchema.model_validate(position_model),
            interviewer=UserSchema.model_validate(interviewer_model),
        )
        return {"result": "success"}