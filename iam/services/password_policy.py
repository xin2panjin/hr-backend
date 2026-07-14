"""统一的本地账号密码策略。"""

from __future__ import annotations

import re


class PasswordPolicyError(ValueError):
    """密码不满足系统安全策略。"""


COMMON_PASSWORDS = frozenset({
    "password", "password123", "12345678", "123456789", "qwerty123",
    "welcome123", "admin123", "letmein123",
})


def validate_password(
    password: str,
    *,
    username: str | None = None,
    email: str | None = None,
) -> None:
    """校验注册和重置密码共用的最小安全要求。"""

    if not 12 <= len(password) <= 128:
        raise PasswordPolicyError("密码长度必须为 12 至 128 位")
    if any(character.isspace() for character in password):
        raise PasswordPolicyError("密码不能包含空白字符")
    if not re.search(r"[a-z]", password):
        raise PasswordPolicyError("密码必须包含小写字母")
    if not re.search(r"[A-Z]", password):
        raise PasswordPolicyError("密码必须包含大写字母")
    if not re.search(r"\d", password):
        raise PasswordPolicyError("密码必须包含数字")
    if not re.search(r"[^A-Za-z0-9]", password):
        raise PasswordPolicyError("密码必须包含特殊字符")

    normalized_password = password.casefold()
    if normalized_password in COMMON_PASSWORDS:
        raise PasswordPolicyError("密码过于常见，请使用更复杂的密码")

    identifiers = [username, email.split("@", 1)[0] if email else None]
    if any(
        identifier and len(identifier.strip()) >= 3
        and identifier.strip().casefold() in normalized_password
        for identifier in identifiers
    ):
        raise PasswordPolicyError("密码不能包含用户名或邮箱前缀")
