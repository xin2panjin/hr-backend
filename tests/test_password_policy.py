import pytest

from iam.services.password_policy import PasswordPolicyError, validate_password


def test_password_policy_accepts_complex_password():
    validate_password("Secure!Pass2026", username="leo", email="leo@example.com")


@pytest.mark.parametrize(
    ("password", "message"),
    [
        ("Short!2026", "长度"),
        ("alllowercase!2026", "大写"),
        ("ALLUPPERCASE!2026", "小写"),
        ("NoDigits!Password", "数字"),
        ("NoSymbolPassword2026", "特殊字符"),
        ("Secure Pass!2026", "空白"),
    ],
)
def test_password_policy_rejects_weak_password(password, message):
    with pytest.raises(PasswordPolicyError, match=message):
        validate_password(password)


def test_password_policy_rejects_username_or_email_prefix():
    with pytest.raises(PasswordPolicyError, match="用户名"):
        validate_password("Alice!Secure2026", username="alice", email="alice@example.com")
