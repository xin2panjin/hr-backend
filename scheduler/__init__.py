# uv add apscheduler

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from core.email_bot import EmailBot
from core.email_bot.settings import EmailBotSettings
from loguru import logger
from settings import settings
from core.cache import HRCache
from services.candidate_workflow_service import (
    CandidateEmailNotFoundError,
    CandidateWorkflowService,
)

scheduler = AsyncIOScheduler()


async def poll_and_process_emails(bot: EmailBot, state: dict):
    try:
        last_uid = state.get("last_uid")
        if last_uid is None:
            last_uid = await bot.get_max_uid() or 0
        state["last_uid"] = last_uid
        logger.info(f"Initialized last_uid={last_uid}")

        new_emails = await bot.fetch_since_uid(last_uid)
        if not new_emails:
            return

        new_emails.sort(key=lambda e: int(e.uid))

        workflow_service = CandidateWorkflowService()
        for mail in new_emails:
            sender_email = (mail.from_.address or "").strip().lower()
            if sender_email == bot.settings.email.lower():
                await _advance_email_uid(state, mail.uid)
                continue

            try:
                response = await workflow_service.on_candidate_email_received(
                    from_email=sender_email,
                    content=mail.text or mail.html or "",
                )
            except CandidateEmailNotFoundError:
                # 收件箱也会接收账单、系统通知等非候选人邮件；这类邮件无需重试。
                logger.info(
                    f"Skipped non-candidate email: sender={sender_email}, uid={mail.uid}"
                )
                await _advance_email_uid(state, mail.uid)
                continue
            except Exception as exc:
                # 保留当前 UID，让下次轮询重试，避免真正的候选人邮件被静默丢弃。
                logger.exception(
                    f"Failed to process candidate email: sender={sender_email}, "
                    f"uid={mail.uid}, error={exc}"
                )
                break

            logger.info(
                f"Processed email from {sender_email}, response: {response}"
            )
            await _advance_email_uid(state, mail.uid)

        logger.info(f"Processed {len(new_emails)} new emails, last_uid now {state['last_uid']}")

    except Exception as e:
        logger.exception(f"Failed to poll and process emails: {e}")


async def _advance_email_uid(state: dict, uid: str | int) -> None:
    """更新内存与 Redis 中的邮箱游标，避免已处理邮件重复触发。"""

    state["last_uid"] = max(int(state["last_uid"]), int(uid))
    cache = HRCache()
    await cache.set_email_last_uid(state["last_uid"])


async def start_email_polling():
    """Initializes and starts the email polling scheduler."""
    email_settings = EmailBotSettings(
        imap_host=settings.EMAIL_BOT_IMAP_HOST,
        smtp_host=settings.EMAIL_BOT_SMTP_HOST,
        email=settings.EMAIL_BOT_EMAIL,
        password=settings.EMAIL_BOT_PASSWORD,
    )
    cache = HRCache()
    last_uid = await cache.get_email_last_uid()
    state: dict = {"last_uid": last_uid}

    bot = EmailBot(email_settings)
    await bot.connect()

    scheduler.add_job(poll_and_process_emails, "interval", seconds=15, args=[bot, state], max_instances=1)
    scheduler.start()
    logger.info("Scheduler started, polling inbox...")
    return bot, scheduler
