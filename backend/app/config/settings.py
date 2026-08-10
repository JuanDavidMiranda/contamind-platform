import secrets
from functools import lru_cache
from typing import Literal

from cryptography.fernet import Fernet
from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    APP_NAME: str = "ContaMind AI"
    VERSION: str = "0.1.0"
    DESCRIPTION: str = "Plataforma para automatización financiera y contable."
    ENVIRONMENT: Literal["development", "test", "staging", "production"] = "development"
    DEBUG: bool = True
    API_V1_PREFIX: str = "/api/v1"
    CORS_ORIGINS: list[str] = [
        "http://localhost:3000",
        "http://localhost:5173",
    ]
    DATABASE_URL: str | None = None
    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: int = 5433
    POSTGRES_USER: str = "contamind"
    POSTGRES_PASSWORD: str = "contamind"
    POSTGRES_DB: str = "contamind"
    AUTH_SECRET_KEY: str | None = None
    PROVIDER_CREDENTIALS_MASTER_KEY: str | None = None
    AUTH_TOKEN_TTL_MINUTES: int = 480
    PLATFORM_ADMIN_EMAILS: str = ""
    FEATURE_FLAGS: dict[str, bool] = {}
    SESSION_MAX_ACTIVE: int = 1000
    SESSION_TTL_SECONDS: int = 3600
    MAX_IMPORT_FILE_BYTES: int = 5_000_000

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    @model_validator(mode="after")
    def _resolve_secret(self) -> "Settings":
        if self.DATABASE_URL is None:
            self.DATABASE_URL = (
                f"postgresql+psycopg2://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
                f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
            )
        if self.ENVIRONMENT in ("staging", "production") and not self.AUTH_SECRET_KEY:
            raise ValueError(
                "AUTH_SECRET_KEY es obligatoria en los ambientes "
                "staging y production. Defínela en el entorno."
            )
        if self.ENVIRONMENT in ("staging", "production") and not self.PROVIDER_CREDENTIALS_MASTER_KEY:
            raise ValueError(
                "PROVIDER_CREDENTIALS_MASTER_KEY es obligatoria en los ambientes "
                "staging y production."
            )
        if self.PROVIDER_CREDENTIALS_MASTER_KEY:
            try:
                Fernet(self.PROVIDER_CREDENTIALS_MASTER_KEY.encode("ascii"))
            except (UnicodeEncodeError, ValueError) as exc:
                raise ValueError(
                    "PROVIDER_CREDENTIALS_MASTER_KEY debe ser una clave Fernet válida."
                ) from exc
        if self.AUTH_SECRET_KEY is None:
            self.AUTH_SECRET_KEY = secrets.token_hex(32)
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
