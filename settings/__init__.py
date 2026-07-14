# from datetime import timedelta
#
# from pydantic_settings import BaseSettings
# from pydantic import computed_field, Field
# import os
#
# BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
#
#
# class Settings(BaseSettings):
#     # DB
#     DB_USERNAME: str = "postgres"
#     DB_PASSWORD: str = "root"
#     DB_HOST: str = "127.0.0.1"
#     DB_PORT: int = 5432
#     DB_NAME: str = "hr_system"
#     DB_AGENT_NAME: str = "hr_system_agent"
#
#     JWT_SECRET_KEY: str = "sfsdfsadfsdfjgafsd"
#     # access_token：一般是2个小时过期
#     # refresh_token：30天过期
#     JWT_ACCESS_TOKEN_EXPIRES: timedelta = timedelta(days=365)
#     JWT_REFRESH_TOKEN_EXPIRES: timedelta = timedelta(days=365)
#
#     # redis配置
#     REDIS_HOST: str = "127.0.0.1"
#     REDIS_PORT: int = 6379
#
#     # 邀请码过期时间
#     INVITE_CODE_EXPIRE: int = 60*60*24*2
#
#     # 邮箱相关的配置
#     MAIL_USERNAME: str = Field(..., validation_alias="MAIL_USERNAME")
#     MAIL_PASSWORD: str = Field(..., validation_alias="MAIL_PASSWORD")
#     MAIL_FROM: str = Field(..., validation_alias="MAIL_USERNAME")
#     MAIL_PORT: int = 587
#     MAIL_SERVER: str = "smtp.qq.com"
#     MAIL_FROM_NAME: str = "知了课堂"
#     MAIL_STARTTLS: bool = True
#     MAIL_SSL_TLS: bool = False
#
#     # 邮箱机器人配置
#     EMAIL_BOT_IMAP_HOST: str = "imap.qq.com"
#     EMAIL_BOT_SMTP_HOST: str = "smtp.qq.com"
#     EMAIL_BOT_EMAIL: str = Field(..., validation_alias="MAIL_USERNAME")
#     EMAIL_BOT_PASSWORD: str = Field(..., validation_alias="MAIL_PASSWORD")
#
#     # 阿里云百炼平台的API_KEY
#     DASHSCOPE_API_KEY: str = Field(..., validation_alias="DASHSCOPE_API_KEY")
#
#
#     # 钉钉相关的配置
#     DINGTALK_CLIENT_ID: str = Field(..., validation_alias="DINGTALK_APP_KEY")
#     DINGTALK_CLIENT_SECRET: str = Field(..., validation_alias="DINGTALK_APP_SECRET")
#
#     # 前端和后端的域名
#     BACKEND_BASE_URL: str = "https://shaina-changeless-danika.ngrok-free.dev"
#
#     # 简历上传存储路径
#     RESUME_DIR: str = os.path.join(BASE_DIR, "upload")
#
#     # Paddle OCR Access Token
#     PADDLE_OCR_ACCESS_TOKEN: str = Field(..., validation_alias="PADDLE_OCR_ACCESS_TOKEN")
#
#     DEBUG: bool = True
#
#     @computed_field
#     @property
#     def DATABASE_URL(self) -> str:
#         return f"postgresql+psycopg://{self.DB_USERNAME}:{self.DB_PASSWORD}@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"
#
#     @computed_field
#     @property
#     def DATABASE_AGENT_URL(self) -> str:
#         return f"postgresql://{self.DB_USERNAME}:{self.DB_PASSWORD}@{self.DB_HOST}:{self.DB_PORT}/{self.DB_AGENT_NAME}"
#
#
# settings = Settings()
#
# # print(f"settings.password: {settings.MAIL_PASSWORD1}")

import json
import os
from datetime import timedelta
from typing import Annotated, Literal

from pydantic_settings import BaseSettings, SettingsConfigDict, NoDecode
from pydantic import computed_field, Field, field_validator

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )
    # DB
    DB_USERNAME: str = Field(..., validation_alias="DB_USERNAME")
    DB_PASSWORD: str = Field(..., validation_alias="DB_PASSWORD")
    DB_HOST: str = Field(..., validation_alias="DB_HOST")
    DB_PORT: int = Field(..., validation_alias="DB_PORT")
    DB_NAME: str = Field("hr_system", validation_alias="DB_NAME")
    DB_AGENT_NAME: str = Field("hr_system_agent", validation_alias="DB_AGENT_NAME")

    JWT_SECRET_KEY: str = Field(..., validation_alias="JWT_SECRET_KEY")
    # Access Token 必须短生命周期；Refresh Token 仍以天为单位管理。
    JWT_ACCESS_TOKEN_EXPIRES_MINUTES: int = Field(
        30,
        ge=5,
        le=120,
        validation_alias="JWT_ACCESS_TOKEN_EXPIRES_MINUTES",
    )
    JWT_REFRESH_TOKEN_EXPIRES_DAYS: int = Field(
        30,
        validation_alias="JWT_REFRESH_TOKEN_EXPIRES_DAYS",
    )

    # redis配置
    REDIS_HOST: str = Field('127.0.0.1', validation_alias="REDIS_HOST")
    REDIS_PORT: int = Field(6389, validation_alias="REDIS_PORT")

    # 邀请码过期时间
    INVITE_CODE_EXPIRE_SECONDS: int = Field(
        60 * 60 * 24 * 2,
        validation_alias="INVITE_CODE_EXPIRE_SECONDS",
    )

    # 邮箱相关的配置
    MAIL_USERNAME: str = Field(..., validation_alias="MAIL_USERNAME")
    MAIL_PASSWORD: str = Field(..., validation_alias="MAIL_PASSWORD")
    MAIL_FROM: str = Field(..., validation_alias="MAIL_USERNAME")
    MAIL_PORT: int = Field(587, validation_alias="MAIL_PORT")
    MAIL_SERVER: str = Field("smtp.qq.com", validation_alias="MAIL_SERVER")
    MAIL_FROM_NAME: str = Field("X公司HR部门", validation_alias="MAIL_FROM_NAME")
    MAIL_STARTTLS: bool = Field(True, validation_alias="MAIL_STARTTLS")
    MAIL_SSL_TLS: bool = Field(False, validation_alias="MAIL_SSL_TLS")
    ENABLE_EMAIL_POLLING: bool = Field(False, validation_alias="ENABLE_EMAIL_POLLING")

    # 邮箱机器人配置
    EMAIL_BOT_IMAP_HOST: str = Field("imap.qq.com", validation_alias="EMAIL_BOT_IMAP_HOST")
    EMAIL_BOT_SMTP_HOST: str = Field("smtp.qq.com", validation_alias="EMAIL_BOT_SMTP_HOST")
    EMAIL_BOT_EMAIL: str = Field(..., validation_alias="MAIL_USERNAME")
    EMAIL_BOT_PASSWORD: str = Field(..., validation_alias="MAIL_PASSWORD")

    # 阿里云百炼平台的 API_KEY
    DASHSCOPE_API_KEY: str = Field(..., validation_alias="DASHSCOPE_API_KEY")

    # 大模型配置：模型会持续迭代，放到 .env 中便于升级，不需要每次修改业务代码
    LLM_BASE_URL: str = Field(
        "https://dashscope.aliyuncs.com/compatible-mode/v1",
        validation_alias="LLM_BASE_URL",
    )
    QWEN_MODEL: str = Field("qwen3.7-plus", validation_alias="QWEN_MODEL")
    DEEPSEEK_MODEL: str = Field("deepseek-v4-flash", validation_alias="DEEPSEEK_MODEL")


    # 钉钉相关的配置
    DINGTALK_CLIENT_ID: str = Field(..., validation_alias="DINGTALK_APP_KEY")
    DINGTALK_CLIENT_SECRET: str = Field(..., validation_alias="DINGTALK_APP_SECRET")

    # Milvus 向量库配置
    MILVUS_URI: str = Field("http://127.0.0.1:19530", validation_alias="MILVUS_URI")
    MILVUS_TOKEN: str | None = Field(None, validation_alias="MILVUS_TOKEN")
    MILVUS_DATABASE: str = Field("default", validation_alias="MILVUS_DATABASE")
    MILVUS_CANDIDATE_COLLECTION: str = Field(
        "candidate_profiles",
        validation_alias="MILVUS_CANDIDATE_COLLECTION",
    )

    # 人才库检索模式：只影响 Milvus 的召回方式，不改变后续 SQL 权限复核。
    TALENT_SEARCH_RETRIEVAL_MODE: Literal["dense", "sparse", "hybrid"] = Field(
        "hybrid",
        validation_alias="TALENT_SEARCH_RETRIEVAL_MODE",
    )

    # 混合检索候选池参数，由 MilvusHybridRetriever 的请求契约使用。
    TALENT_SEARCH_DENSE_RECALL_K: int = Field(
        30,
        ge=1,
        le=100,
        validation_alias="TALENT_SEARCH_DENSE_RECALL_K",
    )
    TALENT_SEARCH_SPARSE_RECALL_K: int = Field(
        30,
        ge=1,
        le=100,
        validation_alias="TALENT_SEARCH_SPARSE_RECALL_K",
    )
    TALENT_SEARCH_HYBRID_LIMIT: int = Field(
        30,
        ge=1,
        le=100,
        validation_alias="TALENT_SEARCH_HYBRID_LIMIT",
    )

    # 默认不启用重排，先验证 Milvus 稠密 + BM25 + RRF 融合链路。
    TALENT_SEARCH_RERANK_ENABLED: bool = Field(
        False,
        validation_alias="TALENT_SEARCH_RERANK_ENABLED",
    )
    # 重排器配置。provider 表示 API 协议，不绑定某个云厂商。
    TALENT_SEARCH_RERANK_PROVIDER: Literal[
        "noop", "cohere_compatible", "dashscope_native"
    ] = Field(
        "noop",
        validation_alias="TALENT_SEARCH_RERANK_PROVIDER",
    )
    TALENT_SEARCH_RERANK_MODEL: str | None = Field(
        "qwen3-rerank",
        validation_alias="TALENT_SEARCH_RERANK_MODEL",
    )
    # 填写完整的 Rerank 请求地址。不同云平台的路径不统一，因此不在业务代码中
    # 拼接 URL；例如 DashScope qwen3-rerank 是 .../v1/reranks。
    TALENT_SEARCH_RERANK_BASE_URL: str | None = Field(
        "https://dashscope.aliyuncs.com/compatible-api/v1/reranks",
        validation_alias="TALENT_SEARCH_RERANK_BASE_URL",
    )
    TALENT_SEARCH_RERANK_API_KEY: str | None = Field(
        None,
        validation_alias="TALENT_SEARCH_RERANK_API_KEY",
    )
    TALENT_SEARCH_RERANK_TIMEOUT_SECONDS: float = Field(
        20.0,
        gt=0,
        le=120,
        validation_alias="TALENT_SEARCH_RERANK_TIMEOUT_SECONDS",
    )
    TALENT_SEARCH_RERANK_MAX_PROFILE_CHARS: int = Field(
        1500,
        ge=200,
        le=10000,
        validation_alias="TALENT_SEARCH_RERANK_MAX_PROFILE_CHARS",
    )
    # Embedding 模型配置
    EMBEDDING_MODEL: str = Field("text-embedding-v4", validation_alias="EMBEDDING_MODEL")
    EMBEDDING_BASE_URL: str = Field(
        "https://dashscope.aliyuncs.com/compatible-mode/v1",
        validation_alias="EMBEDDING_BASE_URL",
    )

    # 候选人画像向量维度，必须和后续 Embedding 模型输出维度一致
    MILVUS_CANDIDATE_VECTOR_DIM: int = Field(
        1024,
        validation_alias="MILVUS_CANDIDATE_VECTOR_DIM",
    )

    # 前端和后端的域名
    BACKEND_BASE_URL: str = Field("http://127.0.0.1:8000/", validation_alias="BACKEND_BASE_URL")

    # 简历上传存储路径
    RESUME_DIR: str = Field(
        os.path.join(BASE_DIR, "upload"),
        validation_alias="RESUME_DIR",
    )

    # Paddle OCR Access Token
    PADDLE_OCR_ACCESS_TOKEN: str = Field(..., validation_alias="PADDLE_OCR_ACCESS_TOKEN")

    # CORS 允许的前端来源。不同环境的前端域名不同，必须放到 .env 中配置。
    # 支持两种写法：
    # 1. CORS_ORIGINS=http://localhost:5173,https://hr.example.com
    # 2. CORS_ORIGINS=["http://localhost:5173","https://hr.example.com"]
    CORS_ORIGINS: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:5173"],
        validation_alias="CORS_ORIGINS",
    )

    DEBUG: bool = Field(False, validation_alias="DEBUG")

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def parse_cors_origins(cls, value):
        """兼容逗号分隔和 JSON 数组两种 CORS 配置格式。"""

        if value is None or isinstance(value, list):
            return value

        if not isinstance(value, str):
            return value

        value = value.strip()
        if not value:
            return []

        if value.startswith("["):
            parsed = json.loads(value)
            if not isinstance(parsed, list):
                raise ValueError("CORS_ORIGINS JSON 配置必须是数组")
            return [str(origin).strip() for origin in parsed if str(origin).strip()]

        return [origin.strip() for origin in value.split(",") if origin.strip()]

    @property
    def JWT_ACCESS_TOKEN_EXPIRES(self) -> timedelta:
        """返回短生命周期 access token 的有效期。"""

        return timedelta(minutes=self.JWT_ACCESS_TOKEN_EXPIRES_MINUTES)

    @property
    def JWT_REFRESH_TOKEN_EXPIRES(self) -> timedelta:
        """兼容原有调用方：返回 refresh token 的 timedelta 过期时间。"""

        return timedelta(days=self.JWT_REFRESH_TOKEN_EXPIRES_DAYS)

    @property
    def INVITE_CODE_EXPIRE(self) -> int:
        """兼容原有调用方：返回邀请码过期秒数。"""

        return self.INVITE_CODE_EXPIRE_SECONDS

    @computed_field
    @property
    def DATABASE_URL(self) -> str:
        return f"postgresql+psycopg://{self.DB_USERNAME}:{self.DB_PASSWORD}@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"

    @computed_field
    @property
    def DATABASE_AGENT_URL(self) -> str:
        return f"postgresql://{self.DB_USERNAME}:{self.DB_PASSWORD}@{self.DB_HOST}:{self.DB_PORT}/{self.DB_AGENT_NAME}"


settings = Settings()
