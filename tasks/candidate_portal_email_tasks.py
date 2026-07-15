from fastapi_mail import MessageSchema

from tasks.email_tasks import send_email_task


async def send_candidate_portal_code_email_task(email: str, code: str) -> None:
    await send_email_task(MessageSchema(
        subject="招聘系统登录验证码",
        recipients=[email],
        body=f"您的候选人门户验证码为：{code}，10 分钟内有效。请勿将验证码提供给他人。",
        subtype="plain",
    ))
