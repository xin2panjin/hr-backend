from fastapi_mail import FastMail, MessageSchema
from aiosmtplib import SMTPResponseException
from loguru import logger
from core.mail import create_mail_instance


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