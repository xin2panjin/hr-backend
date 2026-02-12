from __future__ import annotations

from email.message import EmailMessage
from email.utils import make_msgid
import smtplib

from .imap_client import ImapClient
from .smtp_client import SmtpClient
from .parser import parse_email
from .models import ParsedEmail
from .settings import EmailBotSettings
from loguru import logger


class EmailBot:
    """High-level facade: read/parse/reply/send.

    Typical usage:
        settings = Settings()
        bot = EmailBot(settings)
        async with bot:
            emails = await bot.fetch_latest(limit=10)
    """

    def __init__(self, settings: EmailBotSettings):
        self.settings = settings
        self._imap = ImapClient(
            host=settings.imap_host,
            port=settings.imap_port,
            ssl=settings.imap_ssl,
        )
        self._smtp = SmtpClient(
            host=settings.smtp_host,
            port=settings.smtp_port,
            starttls=settings.smtp_starttls,
        )
        self.is_connected = False

    async def __aenter__(self) -> "EmailBot":
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.close()

    async def connect(self) -> None:
        await self._imap.connect()
        await self._imap.login(self.settings.email, self.settings.password)
        await self._imap.select(self.settings.imap_mailbox)

        await self._smtp.connect()
        await self._smtp.login(self.settings.email, self.settings.password)
        self.is_connected = True

    async def close(self) -> None:
        await self._imap.logout()
        await self._smtp.quit()
        self.is_connected = False

    async def _ensure_connected(self) -> None:
        if not self.is_connected:
            await self.connect()

    async def fetch_latest(self, *, limit: int | None = None, criteria: str = "ALL") -> list[ParsedEmail]:
        await self._ensure_connected()
        limit = limit or self.settings.default_fetch_limit
        uids = await self._imap.get_latest_uids(limit=limit, criteria=criteria)
        pairs = await self._imap.fetch_many_rfc822(uids)
        return [parse_email(uid, msg) for uid, msg in pairs]

    async def fetch_since_uid(self, last_uid: int, *, criteria: str = "ALL") -> list[ParsedEmail]:
        await self._ensure_connected()
        # Using UID SEARCH with a range.
        # Example: UID 123:*  (inclusive)
        uids = await self._imap.search_uids(f"UID {last_uid + 1}:*")
        if criteria and criteria not in {"ALL", "(ALL)"}:
            # If user wants UNSEEN etc. we can combine. Many servers accept: (UID x:* UNSEEN)
            uids2 = await self._imap.search_uids(f"(UID {last_uid + 1}:* {criteria.strip('()')})")
            uids = uids2
        pairs = await self._imap.fetch_many_rfc822(uids)
        return [parse_email(uid, msg) for uid, msg in pairs]

    async def get_max_uid(self) -> int | None:
        await self._ensure_connected()
        return await self._imap.get_max_uid()

    async def send_email(
        self,
        *,
        to: str | list[str],
        subject: str,
        text: str,
        html: str | None = None,
        cc: str | list[str] | None = None,
    ) -> None:
        await self._ensure_connected()
        msg = EmailMessage()
        msg["From"] = self.settings.email
        msg["To"] = ", ".join(to) if isinstance(to, list) else to
        if cc:
            msg["Cc"] = ", ".join(cc) if isinstance(cc, list) else cc
        msg["Subject"] = subject
        msg["Message-ID"] = make_msgid()

        msg.set_content(text)
        if html:
            msg.add_alternative(html, subtype="html")

        try:
            await self._smtp.send_message(msg)
        except smtplib.SMTPServerDisconnected:
            logger.warning("SMTP disconnected. Reconnecting and retrying...")
            await self._reconnect_smtp()
            await self._smtp.send_message(msg)  # Retry once

    async def _reconnect_smtp(self):
        logger.info("Reconnecting SMTP client...")
        await self._smtp.quit()  # Gracefully close old connection if possible
        await self._smtp.connect()
        await self._smtp.login(self.settings.email, self.settings.password)

    async def reply(
        self,
        email: ParsedEmail,
        *,
        text: str,
        subject_prefix: str = "Re: ",
    ) -> None:
        """Reply to a parsed email.

        - Replies to Reply-To if present, else From
        - Adds In-Reply-To and References for proper threading
        """

        raw = email.raw
        reply_to = (raw.get("Reply-To") or "").strip() or email.from_.address
        if not reply_to:
            raise ValueError("Cannot reply: missing sender address")

        subject = email.subject
        if subject_prefix and not subject.lower().startswith(subject_prefix.strip().lower()):
            subject = f"{subject_prefix}{subject}"

        msg = EmailMessage()
        msg["From"] = self.settings.email
        msg["To"] = reply_to
        msg["Subject"] = subject
        msg["Message-ID"] = make_msgid()

        if email.message_id:
            msg["In-Reply-To"] = email.message_id
            refs = (raw.get("References") or "").strip()
            msg["References"] = (refs + " " + email.message_id).strip() if refs else email.message_id

        msg.set_content(text)
        try:
            await self._smtp.send_message(msg)
        except smtplib.SMTPServerDisconnected:
            logger.warning("SMTP disconnected. Reconnecting and retrying reply...")
            await self._reconnect_smtp()
            await self._smtp.send_message(msg)  # Retry once

        logger.info("Replied to uid={} from={} subject={}", email.uid, email.from_.address, email.subject)

        # 异步标记为已读，不阻塞当前回复流程
        try:
            import asyncio

            if email.uid is not None:
                asyncio.create_task(self._imap.mark_seen(str(email.uid)))
        except Exception as e:
            logger.exception("schedule mark_seen failed uid=%s: %s", email.uid, e)
