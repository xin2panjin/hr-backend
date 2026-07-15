"""候选人门户认证；与员工 JWT 和服务端员工会话完全隔离。"""

import json
import secrets
import time
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.cache import HRCache
from models.candidate import CandidateModel
from settings import settings


class CandidatePortalAuthService:
    code_prefix = "candidate-portal:login-code:"
    throttle_prefix = "candidate-portal:login-code-throttle:"
    issuer = "hr-candidate-portal"
    audience = "hr-candidate-portal"
    code_ttl_seconds = 10 * 60
    throttle_seconds = 60
    max_code_attempts = 5
    token_ttl = timedelta(hours=12)

    @staticmethod
    def normalize_email(email: str) -> str:
        return email.strip().lower()

    async def send_code(self, *, email: str, cache: HRCache) -> str:
        email = self.normalize_email(email)
        if await cache.get(f"{self.throttle_prefix}{email}") is not None:
            raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="验证码发送过于频繁，请稍后再试")
        code = f"{secrets.randbelow(1_000_000):06d}"
        await cache.set(
            f"{self.code_prefix}{email}",
            json.dumps({"code": code, "attempts": 0, "expires_at": time.time() + self.code_ttl_seconds}),
            ex=self.code_ttl_seconds,
        )
        await cache.set(f"{self.throttle_prefix}{email}", "1", ex=self.throttle_seconds)
        return code

    async def verify_code(self, *, email: str, code: str, cache: HRCache, session: AsyncSession) -> str:
        email = self.normalize_email(email)
        raw = await cache.get(f"{self.code_prefix}{email}")
        try:
            payload = json.loads(raw) if raw else {}
            cached_code = payload.get("code")
        except (TypeError, json.JSONDecodeError):
            payload = {}
            cached_code = None
        remaining_seconds = max(0, int(float(payload.get("expires_at", 0)) - time.time()))
        if not cached_code or remaining_seconds <= 0:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="验证码错误或已过期")
        if not secrets.compare_digest(str(cached_code), code):
            attempts = int(payload.get("attempts", 0)) + 1
            if attempts >= self.max_code_attempts:
                await cache.set(f"{self.code_prefix}{email}", json.dumps({"code": "locked"}), ex=60)
                raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="验证码错误次数过多，请重新获取验证码")
            payload["attempts"] = attempts
            await cache.set(f"{self.code_prefix}{email}", json.dumps(payload), ex=max(1, remaining_seconds))
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"验证码错误，还可尝试 {self.max_code_attempts - attempts} 次")

        candidate_exists = await session.scalar(
            select(CandidateModel.id).where(func.lower(CandidateModel.email) == email).limit(1)
        )
        if not candidate_exists:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="该邮箱没有可访问的投递记录")
        # RedisBackend.clear 的语义是按命名空间清理，不能用于单个验证码键；覆盖为一分钟无效值。
        await cache.set(f"{self.code_prefix}{email}", json.dumps({"code": "used"}), ex=1)
        return self.issue_access_token(email)

    def issue_access_token(self, email: str) -> str:
        now = datetime.now(timezone.utc)
        return jwt.encode(
            {
                "sub": self.normalize_email(email),
                "typ": "candidate_portal",
                "iss": self.issuer,
                "aud": self.audience,
                "iat": now,
                "nbf": now,
                "exp": now + self.token_ttl,
            },
            settings.JWT_SECRET_KEY,
            algorithm="HS256",
        )

    def decode_access_token(self, token: str) -> str:
        try:
            claims = jwt.decode(
                token,
                settings.JWT_SECRET_KEY,
                algorithms=["HS256"],
                audience=self.audience,
                issuer=self.issuer,
                options={"require": ["sub", "typ", "iat", "nbf", "exp"]},
            )
        except jwt.InvalidTokenError as exc:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="候选人登录已失效") from exc
        if claims.get("typ") != "candidate_portal":
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="候选人登录令牌类型错误")
        return self.normalize_email(str(claims["sub"]))
