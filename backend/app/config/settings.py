from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    APP_NAME: str = "ContaMind AI"
    VERSION: str = "0.1.0"
    DESCRIPTION: str = "Plataforma para automatización financiera y contable."
    ENVIRONMENT: Literal["development", "staging", "production"] = "development"
    DEBUG: bool = True
    API_V1_PREFIX: str = "/api/v1"
    CORS_ORIGINS: list[str] = [
        "http://localhost:3000",
        "http://localhost:5173",
    ]
    DATABASE_URL: str = "sqlite:///./contamind.db"
    AUTH_SECRET_KEY: str = "development-only-change-this-secret-key"
    AUTH_TOKEN_TTL_MINUTES: int = 480
    PLATFORM_ADMIN_EMAILS: str = ""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
