from datetime import timedelta

from pydantic_settings import BaseSettings
from pydantic import computed_field
import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class Settings(BaseSettings):
    # DB
    DB_USERNAME: str = "postgres"
    DB_PASSWORD: str = "root"
    DB_HOST: str = "127.0.0.1"
    DB_PORT: int = 5432
    DB_NAME: str = "hr_system"

    JWT_SECRET_KEY: str = "sfsdfsadfsdfjgafsd"
    # access_token：一般是2个小时过期
    # refresh_token：30天过期
    JWT_ACCESS_TOKEN_EXPIRES: timedelta = timedelta(days=365)
    JWT_REFRESH_TOKEN_EXPIRES: timedelta = timedelta(days=365)

    @computed_field
    @property
    def DATABASE_URL(self) -> str:
        return f"postgresql+psycopg://{self.DB_USERNAME}:{self.DB_PASSWORD}@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"


settings = Settings()