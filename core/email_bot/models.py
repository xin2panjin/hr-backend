from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from email.message import Message
from typing import Optional


@dataclass(frozen=True)
class EmailAddress:
    name: str
    address: str


@dataclass(frozen=True)
class ParsedEmail:
    """A parsed email with convenient fields."""

    uid: str
    message_id: str
    subject: str
    from_: EmailAddress
    to: list[EmailAddress]
    cc: list[EmailAddress]
    date: Optional[datetime]

    text: str
    html: str

    raw: Message

