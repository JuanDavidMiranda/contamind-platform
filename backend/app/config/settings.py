import secrets
from functools import lru_cache
from typing import Literal
from urllib.parse import urlparse

from cryptography.fernet import Fernet
from pydantic import Field, SecretStr, model_validator
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
    DIAN_ACQUIRER_URL: str | None = None
    OPENAI_API_KEY: SecretStr | None = None
    OPENAI_MODEL: str = "gpt-5.6-terra"
    OPENAI_TIMEOUT_SECONDS: float = Field(default=20, ge=1, le=120)
    OPENAI_MAX_OUTPUT_TOKENS: int = Field(default=600, ge=64, le=4_000)
    SESSION_MAX_ACTIVE: int = 1000
    SESSION_TTL_SECONDS: int = 3600
    MAX_IMPORT_FILE_BYTES: int = 5_000_000
    PROVIDER_SYNC_MAX_ATTEMPTS: int = Field(default=3, ge=1, le=10)
    PROVIDER_SYNC_RETRY_BASE_SECONDS: int = Field(default=30, ge=1, le=3600)
    PROVIDER_SYNC_RETRY_MAX_SECONDS: int = Field(default=3600, ge=1, le=86_400)
    PROVIDER_SYNC_LEASE_SECONDS: int = Field(default=600, ge=30, le=86_400)
    PROVIDER_SYNC_WORKER_BATCH_SIZE: int = Field(default=10, ge=1, le=100)
    PROVIDER_SYNC_WORKER_POLL_SECONDS: int = Field(default=5, ge=1, le=300)

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    @model_validator(mode="after")
    def _resolve_secret(self) -> "Settings":
        configured_fields = self.model_fields_set
        if self.DATABASE_URL is None:
            self.DATABASE_URL = (
                f"postgresql+psycopg2://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
                f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
            )
        if self.ENVIRONMENT in ("staging", "production"):
            self._validate_protected_environment(configured_fields)
        if (
            self.ENVIRONMENT in ("staging", "production")
            and self.FEATURE_FLAGS.get("LLM_ENABLED", False)
            and (
                not self.OPENAI_API_KEY
                or not self.OPENAI_API_KEY.get_secret_value().strip()
            )
        ):
            raise ValueError(
                "OPENAI_API_KEY es obligatoria cuando LLM_ENABLED está activo "
                "en staging o production."
            )
        if (
            self.ENVIRONMENT in ("staging", "production")
            and self.FEATURE_FLAGS.get("LLM_ENABLED", False)
            and not self.OPENAI_MODEL.strip()
        ):
            raise ValueError(
                "OPENAI_MODEL es obligatoria cuando LLM_ENABLED está activo "
                "en staging o production."
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

    def _validate_protected_environment(self, configured_fields: set[str]) -> None:
        """Evita que una beta externa arranque con valores locales inseguros."""

        if self.DEBUG:
            raise ValueError("DEBUG debe ser false en staging y production.")
        if (
            "DATABASE_URL" not in configured_fields
            or not self.DATABASE_URL
            or not self.DATABASE_URL.startswith("postgresql")
        ):
            raise ValueError(
                "DATABASE_URL debe definir explícitamente una base PostgreSQL en staging y production."
            )
        if "CORS_ORIGINS" not in configured_fields or not self.CORS_ORIGINS:
            raise ValueError("CORS_ORIGINS debe definir los orígenes HTTPS autorizados.")
        if any(
            urlparse(origin).scheme != "https" or not urlparse(origin).netloc
            for origin in self.CORS_ORIGINS
        ):
            raise ValueError("CORS_ORIGINS solo admite URLs HTTPS válidas en staging y production.")
        if not self.AUTH_SECRET_KEY or len(self.AUTH_SECRET_KEY) < 32:
            raise ValueError(
                "AUTH_SECRET_KEY debe tener al menos 32 caracteres en staging y production."
            )
        if not self.PROVIDER_CREDENTIALS_MASTER_KEY:
            raise ValueError(
                "PROVIDER_CREDENTIALS_MASTER_KEY es obligatoria en staging y production."
            )
        if not self.PLATFORM_ADMIN_EMAILS.strip():
            raise ValueError("PLATFORM_ADMIN_EMAILS debe incluir al menos un administrador de plataforma.")

        required_flags = {
            "DIAN_INTEGRATION_ENABLED",
            "DIAN_ELECTRONIC_HABILITATION_ENABLED",
            "SIIGO_INTEGRATION_ENABLED",
            "ALEGRA_INTEGRATION_ENABLED",
            "WORLDOFFICE_INTEGRATION_ENABLED",
            "NOVASOFT_INTEGRATION_ENABLED",
            "SYSCAFE_INTEGRATION_ENABLED",
            "LLM_ENABLED",
            "MOCK_EXTERNAL_SERVICES",
        }
        missing_flags = sorted(required_flags.difference(self.FEATURE_FLAGS))
        if missing_flags:
            raise ValueError(
                "FEATURE_FLAGS debe declarar explícitamente: " + ", ".join(missing_flags) + "."
            )
        if self.FEATURE_FLAGS["MOCK_EXTERNAL_SERVICES"]:
            raise ValueError("MOCK_EXTERNAL_SERVICES debe ser false en staging y production.")


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
