from __future__ import annotations

import re
from datetime import datetime
from email.header import decode_header
from email.message import Message
from email.utils import getaddresses, parsedate_to_datetime
from typing import Optional

from .models import EmailAddress, ParsedEmail


def _decode_maybe(value: str | None) -> str:
    if not value:
        return ""

    parts = decode_header(value)
    out: list[str] = []
    for chunk, charset in parts:
        if isinstance(chunk, bytes):
            cs = (charset or "utf-8").lower() if isinstance(charset, str) or charset is None else "utf-8"

            # Some servers produce non-standard/placeholder charset names like "unknown-8bit".
            if cs in {"unknown-8bit", "x-unknown"}:
                cs = "utf-8"

            try:
                out.append(chunk.decode(cs, errors="replace"))
            except LookupError:
                # Last-resort fallback: latin-1 provides a 1:1 byte mapping and never raises.
                out.append(chunk.decode("latin-1", errors="replace"))
        else:
            out.append(chunk)
    return "".join(out)


def _strip_html(html: str) -> str:
    # Very small helper; keeps dependency-free. Users can swap it with BeautifulSoup if needed.
    html = re.sub(r"<\s*br\s*/?>", "\n", html, flags=re.I)
    html = re.sub(r"</p\s*>", "\n", html, flags=re.I)
    html = re.sub(r"<[^>]+>", "", html)
    return re.sub(r"\n{3,}", "\n\n", html).strip()


def _parse_addresses(header_value: str | None) -> list[EmailAddress]:
    addrs = []
    for name, addr in getaddresses([header_value or ""]):
        if not addr:
            continue
        addrs.append(EmailAddress(name=_decode_maybe(name).strip(), address=addr.strip()))
    return addrs


def _extract_body(msg: Message) -> tuple[str, str]:
    text_parts: list[str] = []
    html_parts: list[str] = []

    if msg.is_multipart():
        for part in msg.walk():
            ctype = (part.get_content_type() or "").lower()
            disp = (part.get("Content-Disposition") or "").lower()
            if "attachment" in disp:
                continue
            if ctype in {"text/plain", "text/html"}:
                payload = part.get_payload(decode=True)
                if payload is None:
                    continue
                charset = part.get_content_charset() or "utf-8"
                try:
                    content = payload.decode(charset, errors="replace")
                except LookupError:
                    content = payload.decode("utf-8", errors="replace")

                if ctype == "text/plain":
                    text_parts.append(content)
                else:
                    html_parts.append(content)
    else:
        ctype = (msg.get_content_type() or "").lower()
        payload = msg.get_payload(decode=True)
        if payload is not None:
            charset = msg.get_content_charset() or "utf-8"
            try:
                content = payload.decode(charset, errors="replace")
            except LookupError:
                content = payload.decode("utf-8", errors="replace")
            if ctype == "text/html":
                html_parts.append(content)
            else:
                text_parts.append(content)

    text = "\n".join([p.strip("\ufeff") for p in text_parts]).strip()
    html = "\n".join(html_parts).strip()
    if not text and html:
        text = _strip_html(html)
    return text, html


def parse_email(uid: str, msg: Message) -> ParsedEmail:
    message_id = (msg.get("Message-ID") or "").strip()
    subject = _decode_maybe(msg.get("Subject"))

    from_list = _parse_addresses(msg.get("From"))
    from_addr = from_list[0] if from_list else EmailAddress(name="", address="")

    to_addrs = _parse_addresses(msg.get("To"))
    cc_addrs = _parse_addresses(msg.get("Cc"))

    date: Optional[datetime] = None
    try:
        if msg.get("Date"):
            date = parsedate_to_datetime(msg.get("Date"))
    except Exception:
        date = None

    text, html = _extract_body(msg)

    return ParsedEmail(
        uid=str(uid),
        message_id=message_id,
        subject=subject,
        from_=from_addr,
        to=to_addrs,
        cc=cc_addrs,
        date=date,
        text=text,
        html=html,
        raw=msg,
    )

