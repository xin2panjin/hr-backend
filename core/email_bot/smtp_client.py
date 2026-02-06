from __future__ import annotations

import asyncio
import smtplib
from email.message import EmailMessage


class SmtpClient:
    """A tiny SMTP client wrapped with asyncio.to_thread."""

    def __init__(
        self,
        host: str,
        port: int = 587,
        *,
        starttls: bool = True,
    ):
        self._host = host
        self._port = port
        self._starttls = starttls
        self._conn: smtplib.SMTP | None = None

    async def connect(self) -> None:
        def _connect():
            conn = smtplib.SMTP(self._host, self._port, timeout=30)
            conn.ehlo()
            if self._starttls:
                conn.starttls()
                conn.ehlo()
            return conn

        self._conn = await asyncio.to_thread(_connect)

    async def login(self, username: str, password: str) -> None:
        if not self._conn:
            raise RuntimeError("SMTP not connected")
        await asyncio.to_thread(self._conn.login, username, password)

    async def send_message(self, msg: EmailMessage) -> None:
        if not self._conn:
            raise RuntimeError("SMTP not connected")
        await asyncio.to_thread(self._conn.send_message, msg)

    async def quit(self) -> None:
        if not self._conn:
            return
        try:
            await asyncio.to_thread(self._conn.quit)
        finally:
            self._conn = None

