"""zhiliao_email

A small async-friendly email automation library.

Public API:
- EmailBot: high level facade to read/parse/reply/send
- Settings: pydantic-settings based configuration

"""

from .settings import EmailBotSettings
from .bot import EmailBot
from .models import ParsedEmail, EmailAddress

__all__ = [
    "EmailBotSettings",
    "EmailBot",
    "ParsedEmail",
    "EmailAddress",
]

