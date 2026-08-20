import pytest
from cryptography.fernet import Fernet

from app.config.settings import Settings

pytestmark = pytest.mark.unit


def protected_settings(**overrides):
    values = {
        "ENVIRONMENT": "production",
        "DEBUG": False,
        "DATABASE_URL": "postgresql+psycopg2://beta_user:beta_password@db.internal/contamind_beta",
        "CORS_ORIGINS": ["https://beta.contamind.test"],
        "AUTH_SECRET_KEY": "a" * 32,
        "PROVIDER_CREDENTIALS_MASTER_KEY": Fernet.generate_key().decode(),
        "PLATFORM_ADMIN_EMAILS": "operator@contamind.test",
        "FEATURE_FLAGS": {
            "DIAN_INTEGRATION_ENABLED": False,
            "DIAN_ELECTRONIC_HABILITATION_ENABLED": False,
            "SIIGO_INTEGRATION_ENABLED": False,
            "ALEGRA_INTEGRATION_ENABLED": False,
            "WORLDOFFICE_INTEGRATION_ENABLED": False,
            "NOVASOFT_INTEGRATION_ENABLED": False,
            "SYSCAFE_INTEGRATION_ENABLED": False,
            "LLM_ENABLED": False,
            "MOCK_EXTERNAL_SERVICES": False,
        },
        "_env_file": None,
    }
    values.update(overrides)
    return Settings(**values)


def test_development_generates_ephemeral_secret():
    settings = Settings(
        ENVIRONMENT="development",
        AUTH_SECRET_KEY=None,
        _env_file=None,
    )
    assert settings.AUTH_SECRET_KEY is not None
    assert len(settings.AUTH_SECRET_KEY) == 64
    assert settings.AUTH_SECRET_KEY != "development-only-change-this-secret-key"


def test_production_requires_secret():
    with pytest.raises(ValueError):
        Settings(
            ENVIRONMENT="production",
            AUTH_SECRET_KEY=None,
            _env_file=None,
        )


def test_staging_requires_secret():
    with pytest.raises(ValueError):
        Settings(
            ENVIRONMENT="staging",
            AUTH_SECRET_KEY=None,
            _env_file=None,
        )


def test_explicit_secret_is_preserved():
    settings = protected_settings(AUTH_SECRET_KEY="configured-secret" * 2)
    assert settings.AUTH_SECRET_KEY == "configured-secret" * 2


def test_production_requires_provider_credentials_master_key():
    with pytest.raises(ValueError):
        protected_settings(PROVIDER_CREDENTIALS_MASTER_KEY=None)


def test_protected_environment_rejects_local_defaults_and_missing_flags():
    with pytest.raises(ValueError, match="DEBUG"):
        protected_settings(DEBUG=True)
    with pytest.raises(ValueError, match="DATABASE_URL"):
        protected_settings(DATABASE_URL="sqlite:///beta.db")
    with pytest.raises(ValueError, match="CORS_ORIGINS"):
        protected_settings(CORS_ORIGINS=["http://localhost:5173"])
    with pytest.raises(ValueError, match="FEATURE_FLAGS"):
        protected_settings(FEATURE_FLAGS={"LLM_ENABLED": False})
    with pytest.raises(ValueError, match="MOCK_EXTERNAL_SERVICES"):
        protected_settings(
            FEATURE_FLAGS={
                "DIAN_INTEGRATION_ENABLED": False,
                "DIAN_ELECTRONIC_HABILITATION_ENABLED": False,
                "SIIGO_INTEGRATION_ENABLED": False,
                "ALEGRA_INTEGRATION_ENABLED": False,
                "WORLDOFFICE_INTEGRATION_ENABLED": False,
                "NOVASOFT_INTEGRATION_ENABLED": False,
                "SYSCAFE_INTEGRATION_ENABLED": False,
                "LLM_ENABLED": False,
                "MOCK_EXTERNAL_SERVICES": True,
            }
        )


def test_provider_credentials_master_key_must_be_a_valid_fernet_key():
    with pytest.raises(ValueError):
        Settings(
            ENVIRONMENT="development",
            PROVIDER_CREDENTIALS_MASTER_KEY="not-a-fernet-key",
            _env_file=None,
        )
