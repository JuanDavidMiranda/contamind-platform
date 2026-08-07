import pytest

from app.config.settings import Settings


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
        _env_file=None,
    )
    assert settings.AUTH_SECRET_KEY == "configured-secret"
