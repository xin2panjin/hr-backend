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

from datetime import timedelta

from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import computed_field, Field
import os

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
    DB_NAME: str = "hr_system"
    DB_AGENT_NAME: str = "hr_system_agent"

    JWT_SECRET_KEY: str = Field(..., validation_alias="JWT_SECRET_KEY")
    # access_token：一般是2个小时过期
    # refresh_token：30天过期
    JWT_ACCESS_TOKEN_EXPIRES: timedelta = timedelta(days=7)
    JWT_REFRESH_TOKEN_EXPIRES: timedelta = timedelta(days=30)

    # redis配置
    REDIS_HOST: str = Field('127.0.0.1', validation_alias="REDIS_HOST")
    REDIS_PORT: int = Field(6389, validation_alias="REDIS_PORT")

    # 邀请码过期时间
    INVITE_CODE_EXPIRE: int = 60*60*24*2

    # 邮箱相关的配置
    MAIL_USERNAME: str = Field(..., validation_alias="MAIL_USERNAME")
    MAIL_PASSWORD: str = Field(..., validation_alias="MAIL_PASSWORD")
    MAIL_FROM: str = Field(..., validation_alias="MAIL_USERNAME")
    MAIL_PORT: int = 587
    MAIL_SERVER: str = "smtp.qq.com"
    MAIL_FROM_NAME: str = "知了课堂"
    MAIL_STARTTLS: bool = True
    MAIL_SSL_TLS: bool = False
    ENABLE_EMAIL_POLLING: bool = Field(False, validation_alias="ENABLE_EMAIL_POLLING")

    # 邮箱机器人配置
    EMAIL_BOT_IMAP_HOST: str = "imap.qq.com"
    EMAIL_BOT_SMTP_HOST: str = "smtp.qq.com"
    EMAIL_BOT_EMAIL: str = Field(..., validation_alias="MAIL_USERNAME")
    EMAIL_BOT_PASSWORD: str = Field(..., validation_alias="MAIL_PASSWORD")

    # 阿里云百炼平台的API_KEY
    DASHSCOPE_API_KEY: str = Field(..., validation_alias="DASHSCOPE_API_KEY")


    # 钉钉相关的配置
    DINGTALK_CLIENT_ID: str = Field(..., validation_alias="DINGTALK_APP_KEY")
    DINGTALK_CLIENT_SECRET: str = Field(..., validation_alias="DINGTALK_APP_SECRET")

    # Milvus 向量库配置
    MILVUS_URI: str = Field("http://127.0.0.1:19530", validation_alias="MILVUS_URI")
    MILVUS_TOKEN: str | None = Field(None, validation_alias="MILVUS_TOKEN")
    MILVUS_DATABASE: str = Field("default", validation_alias="MILVUS_DATABASE")
    MILVUS_CANDIDATE_COLLECTION: str = Field(
        "candidate_profiles_v1",
        validation_alias="MILVUS_CANDIDATE_COLLECTION",
    )

    # 候选人画像向量维度，必须和后续 Embedding 模型输出维度一致
    MILVUS_CANDIDATE_VECTOR_DIM: int = Field(
        1024,
        validation_alias="MILVUS_CANDIDATE_VECTOR_DIM",
    )

    # 前端和后端的域名
    BACKEND_BASE_URL: str = Field("https://shaina-changeless-danika.ngrok-free.dev", validation_alias="BACKEND_BASE_URL")

    # 简历上传存储路径
    RESUME_DIR: str = os.path.join(BASE_DIR, "upload")

    # Paddle OCR Access Token
    PADDLE_OCR_ACCESS_TOKEN: str = Field(..., validation_alias="PADDLE_OCR_ACCESS_TOKEN")

    CORS_ORIGINS: list[str] = ["http://localhost:5173"]

    DEBUG: bool = False

    @computed_field
    @property
    def DATABASE_URL(self) -> str:
        return f"postgresql+psycopg://{self.DB_USERNAME}:{self.DB_PASSWORD}@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"

    @computed_field
    @property
    def DATABASE_AGENT_URL(self) -> str:
        return f"postgresql://{self.DB_USERNAME}:{self.DB_PASSWORD}@{self.DB_HOST}:{self.DB_PORT}/{self.DB_AGENT_NAME}"


settings = Settings()
