from __future__ import annotations

import asyncio
import imaplib
from email import message_from_bytes
from email.message import Message
from typing import Iterable, Optional
from loguru import logger


class ImapClient:
    """A tiny IMAP client wrapped with asyncio.to_thread.

    Note: imaplib is blocking; we offload calls to threads.
    """

    def __init__(self, host: str, port: int = 993, *, ssl: bool = True):
        self._host = host
        self._port = port
        self._ssl = ssl
        self._conn: imaplib.IMAP4 | imaplib.IMAP4_SSL | None = None
        # 保存认证信息以便重连时使用
        self._username: Optional[str] = None
        self._password: Optional[str] = None
        self._mailbox: Optional[str] = None

    async def connect(self) -> None:
        def _connect():
            if self._ssl:
                return imaplib.IMAP4_SSL(self._host, self._port)
            return imaplib.IMAP4(self._host, self._port)

        self._conn = await asyncio.to_thread(_connect)

    async def login(self, username: str, password: str) -> None:
        if not self._conn:
            raise RuntimeError("IMAP not connected")
        await asyncio.to_thread(self._conn.login, username, password)
        # 保存认证信息以便重连时使用
        self._username = username
        self._password = password

    async def select(self, mailbox: str = "INBOX") -> None:
        if not self._conn:
            raise RuntimeError("IMAP not connected")
        await asyncio.to_thread(self._conn.select, mailbox)
        # 保存邮箱名以便重连时使用
        self._mailbox = mailbox

    async def logout(self) -> None:
        if not self._conn:
            return
        try:
            await asyncio.to_thread(self._conn.logout)
        finally:
            self._conn = None

    async def _reconnect(self) -> None:
        """重新连接并恢复登录状态（如果之前已登录）。"""
        logger.info("Reconnecting IMAP client...")
        # 先关闭旧连接
        if self._conn:
            try:
                await asyncio.to_thread(self._conn.logout)
            except Exception:
                pass  # 忽略关闭时的错误
            finally:
                self._conn = None

        # 重新连接
        await self.connect()

        # 如果之前有保存认证信息，自动恢复登录和选择邮箱
        if self._username and self._password:
            await self.login(self._username, self._password)
            if self._mailbox:
                await self.select(self._mailbox)

    async def search_uids(self, criteria: str) -> list[str]:
        """Return UID list matched by criteria.

        Example criteria:
          - "ALL"
          - "UNSEEN"
          - "(UNSEEN)"
        """
        if not self._conn:
            raise RuntimeError("IMAP not connected")

        def _search():
            typ, data = self._conn.uid("SEARCH", None, criteria)
            if typ != "OK":
                raise RuntimeError(f"IMAP SEARCH failed: {typ} {data}")
            raw = data[0] or b""
            return [x.decode() if isinstance(x, bytes) else str(x) for x in raw.split() if x]

        try:
            return await asyncio.to_thread(_search)
        except (imaplib.IMAP4.abort, imaplib.IMAP4.error) as e:
            # 连接异常，尝试重连并重试一次
            logger.warning("IMAP connection aborted during SEARCH, reconnecting and retrying... criteria=%s, error=%s", criteria, e)
            await self._reconnect()
            # 重连后重试
            return await asyncio.to_thread(_search)

    async def fetch_rfc822(self, uid: str) -> Message:
        if not self._conn:
            raise RuntimeError("IMAP not connected")

        def _fetch():
            typ, data = self._conn.uid("FETCH", uid, "(RFC822)")
            if typ != "OK":
                raise RuntimeError(f"IMAP FETCH failed: {typ} {data}")
            # data looks like: [(b'1 (RFC822 {bytes}', b'....'), b')']
            for item in data:
                if isinstance(item, tuple) and len(item) >= 2:
                    return message_from_bytes(item[1])
            raise RuntimeError("IMAP FETCH returned no message")

        try:
            return await asyncio.to_thread(_fetch)
        except (imaplib.IMAP4.abort, imaplib.IMAP4.error) as e:
            # 连接异常，尝试重连并重试一次
            logger.warning("IMAP connection aborted during FETCH, reconnecting and retrying... uid=%s, error=%s", uid, e)
            await self._reconnect()
            # 重连后重试
            return await asyncio.to_thread(_fetch)

    async def fetch_many_rfc822(self, uids: Iterable[str]) -> list[tuple[str, Message]]:
        out: list[tuple[str, Message]] = []
        for uid in uids:
            try:
                msg = await self.fetch_rfc822(uid)
                out.append((str(uid), msg))
            except Exception as e:
                logger.exception("fetch message failed uid=%s: %s", uid, e)
        return out

    async def get_latest_uids(self, limit: int = 10, *, criteria: str = "ALL") -> list[str]:
        uids = await self.search_uids(criteria)
        return uids[-limit:]

    async def get_max_uid(self) -> Optional[int]:
        uids = await self.search_uids("ALL")
        if not uids:
            return None
        try:
            return max(int(x) for x in uids)
        except ValueError:
            return None

    async def mark_seen(self, uid: str) -> None:
        """Mark a single message as \\Seen by UID."""
        if not self._conn:
            raise RuntimeError("IMAP not connected")

        def _store():
            typ, data = self._conn.uid("STORE", uid, "+FLAGS", r"(\\Seen)")
            if typ != "OK":
                raise RuntimeError(f"IMAP STORE \\Seen failed: {typ} {data}")

        try:
            await asyncio.to_thread(_store)
        except (imaplib.IMAP4.abort, imaplib.IMAP4.error) as e:
            logger.warning(
                "IMAP connection aborted during STORE (mark_seen), reconnecting and retrying... uid=%s, error=%s",
                uid,
                e,
            )
            await self._reconnect()
            await asyncio.to_thread(_store)

    async def mark_many_seen(self, uids: Iterable[str]) -> None:
        """Mark multiple messages as \\Seen in one STORE call when possible."""
        uid_list = [str(u) for u in uids]
        if not uid_list:
            return
        if not self._conn:
            raise RuntimeError("IMAP not connected")

        uid_set = ",".join(uid_list)

        def _store_many():
            typ, data = self._conn.uid("STORE", uid_set, "+FLAGS", r"(\\Seen)")
            if typ != "OK":
                raise RuntimeError(f"IMAP STORE \\Seen (many) failed: {typ} {data}")

        try:
            await asyncio.to_thread(_store_many)
        except (imaplib.IMAP4.abort, imaplib.IMAP4.error) as e:
            logger.warning(
                "IMAP connection aborted during STORE (mark_many_seen), reconnecting and retrying... uids=%s, error=%s",
                uid_set,
                e,
            )
            await self._reconnect()
            await asyncio.to_thread(_store_many)
