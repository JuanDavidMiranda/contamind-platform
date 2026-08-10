import pytest

from app.ai.bootstrap import bootstrap as bootstrap_module
from app.ai.tools.registry import ToolRegistry
from app.config import features
from app.config.settings import settings

pytestmark = pytest.mark.unit


def test_feature_flags_default_disabled():
    assert features.is_enabled(features.FEATURE_DIAN_INTEGRATION) is False
    assert features.is_enabled(features.FEATURE_SIIGO_INTEGRATION) is False


def test_enabled_features_exposes_known_flags():
    result = features.enabled_features()
    assert set(result) == {
        "ALEGRA_INTEGRATION_ENABLED",
        "DIAN_INTEGRATION_ENABLED",
        "SIIGO_INTEGRATION_ENABLED",
        "LLM_ENABLED",
        "MOCK_EXTERNAL_SERVICES",
        "WORLDOFFICE_INTEGRATION_ENABLED",
    }


def test_is_enabled_reads_configured_flags(monkeypatch):
    monkeypatch.setattr(
        settings,
        "FEATURE_FLAGS",
        {features.FEATURE_LLM: True},
    )
    assert features.is_enabled(features.FEATURE_LLM) is True


def test_mock_default_is_enabled():
    assert (
        features.is_enabled(features.FEATURE_MOCK_EXTERNAL_SERVICES, default=True)
        is True
    )


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
