import pytest
from cryptography.fernet import Fernet
from pydantic import ValidationError

from app.ai.bootstrap import bootstrap as bootstrap_module
from app.ai.tools.registry import ToolRegistry
from app.config import features
from app.config.settings import Settings, settings

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
            features.FEATURE_DIAN_INTEGRATION: False,
            features.FEATURE_DIAN_ELECTRONIC_HABILITATION: False,
            features.FEATURE_SIIGO_INTEGRATION: False,
            features.FEATURE_ALEGRA_INTEGRATION: False,
            features.FEATURE_WORLDOFFICE_INTEGRATION: False,
            features.FEATURE_NOVASOFT_INTEGRATION: False,
            features.FEATURE_SYSCAFE_INTEGRATION: False,
            features.FEATURE_LLM: False,
            features.FEATURE_MOCK_EXTERNAL_SERVICES: False,
        },
        "_env_file": None,
    }
    values.update(overrides)
    return Settings(**values)


def test_feature_flags_default_disabled():
    assert features.is_enabled(features.FEATURE_DIAN_INTEGRATION) is False
    assert features.is_enabled(features.FEATURE_SIIGO_INTEGRATION) is False


def test_enabled_features_exposes_known_flags():
    result = features.enabled_features()
    assert set(result) == {
        "ALEGRA_INTEGRATION_ENABLED",
        "DIAN_INTEGRATION_ENABLED",
        "DIAN_ELECTRONIC_HABILITATION_ENABLED",
        "SIIGO_INTEGRATION_ENABLED",
        "LLM_ENABLED",
        "MOCK_EXTERNAL_SERVICES",
        "NOVASOFT_INTEGRATION_ENABLED",
        "WORLDOFFICE_INTEGRATION_ENABLED",
        "SYSCAFE_INTEGRATION_ENABLED",
    }


def test_is_enabled_reads_configured_flags(monkeypatch):
    monkeypatch.setattr(
        settings,
        "FEATURE_FLAGS",
        {features.FEATURE_LLM: True},
    )
    assert features.is_enabled(features.FEATURE_LLM) is True


def test_mock_default_is_disabled_without_an_explicit_flag(monkeypatch):
    monkeypatch.setattr(settings, "FEATURE_FLAGS", {})
    assert features.is_enabled(features.FEATURE_MOCK_EXTERNAL_SERVICES) is False


def test_provider_flags_are_disabled_by_default():
    assert features.is_provider_enabled("alegra") is False
    assert features.is_provider_enabled("worldoffice_cloud") is False


def test_is_provider_enabled_reads_provider_feature_flag(monkeypatch):
    monkeypatch.setattr(
        settings,
        "FEATURE_FLAGS",
        {features.FEATURE_ALEGRA_INTEGRATION: True},
    )
    assert features.is_provider_enabled("alegra") is True


def test_production_requires_an_openai_key_when_llm_is_enabled():
    with pytest.raises(ValidationError, match="OPENAI_API_KEY"):
        protected_settings(
            FEATURE_FLAGS={
                **protected_settings().FEATURE_FLAGS,
                features.FEATURE_LLM: True,
            },
            OPENAI_API_KEY=None,
        )


def test_production_requires_an_openai_model_when_llm_is_enabled():
    with pytest.raises(ValidationError, match="OPENAI_MODEL"):
        protected_settings(
            FEATURE_FLAGS={
                **protected_settings().FEATURE_FLAGS,
                features.FEATURE_LLM: True,
            },
            OPENAI_API_KEY="test-api-key",
            OPENAI_MODEL="   ",
        )


def test_bootstrap_registers_mock_when_enabled(monkeypatch):
    monkeypatch.setattr(
        bootstrap_module,
        "is_enabled",
        lambda name, default=False: True,
    )
    registry = ToolRegistry()
    monkeypatch.setattr(bootstrap_module, "registry", registry)

    bootstrap_module.bootstrap()

    assert registry.get("Consultar obligaciones") is not None


def test_bootstrap_skips_mock_when_disabled(monkeypatch):
    monkeypatch.setattr(
        bootstrap_module,
        "is_enabled",
        lambda name, default=False: False,
    )
    registry = ToolRegistry()
    monkeypatch.setattr(bootstrap_module, "registry", registry)

    bootstrap_module.bootstrap()

    assert "Consultar obligaciones" not in registry.list()
