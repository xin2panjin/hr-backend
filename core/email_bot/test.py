import asyncio
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import os

from bot import EmailBot, EmailBotSettings
from loguru import logger

REPLY_TEXT = "我已经收到，会尽快处理。"


async def poll_and_reply(bot: EmailBot, state: dict):
    try:
        last_uid = state.get("last_uid")
        if last_uid is None:
            state["last_uid"] = await bot.get_max_uid() or 0
            logger.info("init last_uid={}", state["last_uid"])
            return

        new_emails = await bot.fetch_since_uid(last_uid)
        if not new_emails:
            return

        # process in UID order
        new_emails.sort(key=lambda e: int(e.uid) if str(e.uid).isdigit() else 0)

        for mail in new_emails:
            # avoid replying to self
            if mail.from_.address.lower() == bot.settings.email.lower():
                continue
            await bot.reply(mail, text=REPLY_TEXT)
            state["last_uid"] = max(state["last_uid"], int(mail.uid)) if str(mail.uid).isdigit() else state["last_uid"]

        logger.info("processed {} new emails, last_uid now {}", len(new_emails), state["last_uid"])

    except Exception as e:
        logger.exception("poll_and_reply failed: {}", e)


async def main():
    settings = EmailBotSettings(
        imap_host="imap.qq.com",
        smtp_host="smtp.qq.com",
        email=os.getenv("MAIL_USERNAME"),
        password=os.getenv("MAIL_PASSWORD"),
    )
    state: dict = {"last_uid": None}

    async with EmailBot(settings) as bot:
        scheduler = AsyncIOScheduler()
        scheduler.add_job(poll_and_reply, "interval", seconds=15, args=[bot, state], max_instances=1)
        scheduler.start()

        logger.info("scheduler started, polling inbox...")
        # keep running
        await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main())