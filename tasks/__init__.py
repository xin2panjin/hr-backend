from fastapi_mail import FastMail, MessageSchema
from aiosmtplib import SMTPResponseException
from loguru import logger
from core.mail import create_mail_instance
from models import AsyncSessionFactory, AsyncSession
from repository.candidate_repo import ResumeRepo, ResumeModel
import os

from schemas.position_schema import PositionSchema
from schemas.user_schema import UserSchema
from settings import settings
from core.ocr import PaddleOcr
from dependencies import get_cache_instance, HRCache
from core.cache import TaskInfoSchema
from agents.resume import extract_candidate_info
from schemas.agent_schema import AgentCandidateSchema
from schemas.candidate_schema import CandidateSchema
from agents.candidate import CandidateProcessAgent
from langchain.messages import HumanMessage


async def send_email_task(message: MessageSchema):
    # 发送邮件
    mail: FastMail = create_mail_instance()
    try:
        await mail.send_message(message)
    except SMTPResponseException as e:
        if e.code == -1 and b'\\x00\\x00\\x00' in str(e).encode():
            logger.info("⚠️ 忽略 QQ 邮箱 SMTP 关闭阶段的非标准响应（邮件已成功发送）", enqueue=True)
        else:
            logger.error(f"邮件发送失败！{e}")

async def send_invite_email_task(
    email: str,
    invite_code: str
):
    # 发送邮件
    message = MessageSchema(
        subject="【知了课堂】注册邀请",
        recipients=[email],
        body=f"您好，您的邮箱是：{email}，验证码是：{invite_code}，一天内有效。",
        subtype="plain"
    )
    await send_email_task(message)

async def ocr_parse_resume_task(
    resume_id: str,
    task_id: str
):
    async with AsyncSessionFactory() as session:
        async with session.begin():
            resume_repo = ResumeRepo(session=session)
            resume: ResumeModel = await resume_repo.get_by_id(resume_id)
    file_path = os.path.join(settings.RESUME_DIR, resume.file_path)
    # 1. 设置当前的状态为pending，任务的执行状态和过程中的数据可以存储在redis中
    cache: HRCache = get_cache_instance()
    await cache.set_task_info(TaskInfoSchema(task_id=task_id, status="pending"))
    try:
        paddle_ocr = PaddleOcr()
        job_id = await paddle_ocr.create_job(file_path)
        jsonl_url = await paddle_ocr.poll_for_state(job_id)
        contents = await paddle_ocr.fetch_parsed_contents(jsonl_url)
        content = "\n\n".join(contents)
        # TODO： 将content丢给大模型，让大模型识别其中的内容，比如姓名、性别、年龄、技能、教育经历、工作经历
        candidate_info: AgentCandidateSchema = await extract_candidate_info(content)
        # 2. 设置当前状态为done
        result = {"content": content}
        await cache.set_task_info(TaskInfoSchema(task_id=task_id, status="done", result=candidate_info))
    except Exception as e:
        # 3. 如果出现了异常，就把状态设置failed
        await cache.set_task_info(TaskInfoSchema(task_id=task_id, status="failed", error=str(e)))


async def run_candidate_agent(
    candidate: CandidateSchema,
    position: PositionSchema,
    interviewer: UserSchema
):
    async with CandidateProcessAgent(
        candidate=candidate,
        position=position,
        interviewer=interviewer
    ) as agent:
        response = await agent.ainvoke(
            messages = [{
                "role": "user",
                "content": f"候选人信息：{candidate.model_dump_json()}，职位信息：{position.model_dump_json()}"
            }],
            thread_id=candidate.email
        )
        print(response)
        return response