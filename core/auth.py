"""JWT 签发与解析。

新令牌使用标准声明并绑定服务端会话；保留旧格式解析，仅用于已签发令牌的
过渡兼容。新登录不会再生成旧格式令牌。
"""

import hashlib
import hmac
import uuid
from datetime import datetime
from enum import StrEnum
from threading import Lock

import jwt
from fastapi import HTTPException, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from settings import settings
from starlette.status import HTTP_401_UNAUTHORIZED, HTTP_403_FORBIDDEN


class SingletonMeta(type):
    _instances = {}
    _lock: Lock = Lock()

    def __call__(cls, *args, **kwargs):
        with cls._lock:
            if cls not in cls._instances:
                cls._instances[cls] = super().__call__(*args, **kwargs)
        return cls._instances[cls]


class TokenTypeEnum(StrEnum):
    ACCESS_TOKEN = "access"
    REFRESH_TOKEN = "refresh"


class AuthHandler(metaclass=SingletonMeta):
    security = HTTPBearer()
    secret = settings.JWT_SECRET_KEY
    issuer = "hr-backend"
    audience = "hr-api"

    def issue_session_tokens(
        self,
        *,
        user_id: str,
        session_id: str,
        authz_version: int,
    ) -> dict[str, object]:
        """为一个已创建或待持久化的会话签发 access/refresh 对。"""

        access_token, access_claims = self._encode_token(
            user_id=user_id,
            session_id=session_id,
            authz_version=authz_version,
            token_type=TokenTypeEnum.ACCESS_TOKEN,
        )
        refresh_token, refresh_claims = self._encode_token(
            user_id=user_id,
            session_id=session_id,
            authz_version=authz_version,
            token_type=TokenTypeEnum.REFRESH_TOKEN,
        )
        return {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "access_claims": access_claims,
            "refresh_claims": refresh_claims,
        }

    # 兼容旧调用方名称；新调用方应使用 issue_session_tokens。
    def encode_login_token(self, user_id: str, session_id: str | None = None, authz_version: int = 1):
        return self.issue_session_tokens(
            user_id=user_id,
            session_id=session_id or uuid.uuid4().hex,
            authz_version=authz_version,
        )

    def _encode_token(
        self,
        *,
        user_id: str,
        session_id: str,
        authz_version: int,
        token_type: TokenTypeEnum,
    ) -> tuple[str, dict[str, object]]:
        now = datetime.now()
        expires_at = now + (
            settings.JWT_ACCESS_TOKEN_EXPIRES
            if token_type == TokenTypeEnum.ACCESS_TOKEN
            else settings.JWT_REFRESH_TOKEN_EXPIRES
        )
        claims: dict[str, object] = {
            "sub": str(user_id),
            "sid": session_id,
            "jti": uuid.uuid4().hex,
            "ver": authz_version,
            "typ": token_type.value,
            "iss": self.issuer,
            "aud": self.audience,
            "iat": int(now.timestamp()),
            "nbf": int(now.timestamp()),
            "exp": int(expires_at.timestamp()),
        }
        return jwt.encode(claims, self.secret, algorithm="HS256"), claims

    def hash_jti(self, jti: str) -> str:
        return hmac.new(self.secret.encode(), jti.encode(), hashlib.sha256).hexdigest()

    def decode_access_token(self, token: str) -> dict[str, object]:
        return self._decode_token(token, TokenTypeEnum.ACCESS_TOKEN, HTTP_403_FORBIDDEN)

    def decode_refresh_token(self, token: str) -> dict[str, object]:
        return self._decode_token(token, TokenTypeEnum.REFRESH_TOKEN, HTTP_401_UNAUTHORIZED)

    def _decode_token(
        self,
        token: str,
        expected_type: TokenTypeEnum,
        error_status: int,
    ) -> dict[str, object]:
        try:
            unverified = jwt.decode(token, options={"verify_signature": False})
            if "typ" not in unverified:
                return self._decode_legacy_token(token, expected_type, error_status)
            claims = jwt.decode(
                token,
                self.secret,
                algorithms=["HS256"],
                audience=self.audience,
                issuer=self.issuer,
                options={"require": ["sub", "sid", "jti", "ver", "typ", "iat", "nbf"]},
            )
            if claims.get("typ") != expected_type.value:
                raise HTTPException(status_code=error_status, detail="Token类型错误！")
            return claims
        except HTTPException:
            raise
        except jwt.ExpiredSignatureError as exc:
            raise HTTPException(status_code=error_status, detail="Token已过期！") from exc
        except jwt.InvalidTokenError as exc:
            raise HTTPException(status_code=error_status, detail="Token不可用！") from exc

    def _decode_legacy_token(
        self,
        token: str,
        expected_type: TokenTypeEnum,
        error_status: int,
    ) -> dict[str, object]:
        """兼容之前 iss=user_id、sub=1/2 的令牌，过期后自然淘汰。"""

        claims = jwt.decode(token, self.secret, algorithms=["HS256"])
        legacy_type = "1" if expected_type == TokenTypeEnum.ACCESS_TOKEN else "2"
        if claims.get("sub") != legacy_type:
            raise HTTPException(status_code=error_status, detail="Token类型错误！")
        return {"sub": claims["iss"], "legacy": True}

    def auth_access_dependency(self, auth: HTTPAuthorizationCredentials = Security(security)):
        return self.decode_access_token(auth.credentials)

    def auth_refresh_dependency(self, auth: HTTPAuthorizationCredentials = Security(security)):
        return self.decode_refresh_token(auth.credentials)
