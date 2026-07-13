"""手工验证邮件机器人轮询与自动回复的示例脚本。

运行：uv run python -m scripts.manual_email_bot
执行前请在 .env 中配置 MAIL_USERNAME 和 MAIL_PASSWORD。
"""

import asyncio
import os

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from loguru import logger

from core.email_bot import EmailBot, EmailBotSettings

REPLY_TEXT = "我已经收到，会尽快处理。"


async def poll_and_reply(bot: EmailBot, state: dict) -> None:
    """轮询新邮件，并对非本人发件的邮件进行自动回复。"""

    try:
        last_uid = state.get("last_uid")
        if last_uid is None:
            state["last_uid"] = await bot.get_max_uid() or 0
            logger.info("init last_uid={}", state["last_uid"])
            return

        new_emails = await bot.fetch_since_uid(last_uid)
        if not new_emails:
            return

        new_emails.sort(key=lambda email: int(email.uid) if str(email.uid).isdigit() else 0)
        for email in new_emails:
            if email.from_.address.lower() == bot.settings.email.lower():
                continue
            await bot.reply(email, text=REPLY_TEXT)
            if str(email.uid).isdigit():
                state["last_uid"] = max(state["last_uid"], int(email.uid))

        logger.info("processed {} new emails, last_uid now {}", len(new_emails), state["last_uid"])
    except Exception as exc:
        logger.exception("poll_and_reply failed: {}", exc)


async def main() -> None:
    """启动仅用于本地手工验证的轮询任务。"""

    email_settings = EmailBotSettings(
        imap_host="imap.qq.com",
        smtp_host="smtp.qq.com",
        email=os.getenv("MAIL_USERNAME"),
        password=os.getenv("MAIL_PASSWORD"),
    )
    state: dict = {"last_uid": None}

    async with EmailBot(email_settings) as bot:
        scheduler = AsyncIOScheduler()
        scheduler.add_job(
            poll_and_reply,
            "interval",
            seconds=15,
            args=[bot, state],
            max_instances=1,
        )
        scheduler.start()
        logger.info("scheduler started, polling inbox...")
        await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main())
