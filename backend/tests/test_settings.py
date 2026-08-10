import pytest
from cryptography.fernet import Fernet

from app.config.settings import Settings

pytestmark = pytest.mark.unit


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
    settings = Settings(
        ENVIRONMENT="production",
        AUTH_SECRET_KEY="configured-secret",
        PROVIDER_CREDENTIALS_MASTER_KEY=Fernet.generate_key().decode(),
        _env_file=None,
    )
    assert settings.AUTH_SECRET_KEY == "configured-secret"


def test_production_requires_provider_credentials_master_key():
    with pytest.raises(ValueError):
        Settings(
            ENVIRONMENT="production",
            AUTH_SECRET_KEY="configured-secret",
            PROVIDER_CREDENTIALS_MASTER_KEY=None,
            _env_file=None,
        )


def test_provider_credentials_master_key_must_be_a_valid_fernet_key():
    with pytest.raises(ValueError):
        Settings(
            ENVIRONMENT="development",
            PROVIDER_CREDENTIALS_MASTER_KEY="not-a-fernet-key",
            _env_file=None,
        )
