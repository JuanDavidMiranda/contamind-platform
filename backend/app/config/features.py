from app.config.settings import settings

FEATURE_DIAN_INTEGRATION = "DIAN_INTEGRATION_ENABLED"
FEATURE_SIIGO_INTEGRATION = "SIIGO_INTEGRATION_ENABLED"
FEATURE_ALEGRA_INTEGRATION = "ALEGRA_INTEGRATION_ENABLED"
FEATURE_WORLDOFFICE_INTEGRATION = "WORLDOFFICE_INTEGRATION_ENABLED"
FEATURE_NOVASOFT_INTEGRATION = "NOVASOFT_INTEGRATION_ENABLED"
FEATURE_SYSCAFE_INTEGRATION = "SYSCAFE_INTEGRATION_ENABLED"
FEATURE_LLM = "LLM_ENABLED"
FEATURE_MOCK_EXTERNAL_SERVICES = "MOCK_EXTERNAL_SERVICES"

_PROVIDER_FLAGS = {
    "dian": FEATURE_DIAN_INTEGRATION,
    "siigo": FEATURE_SIIGO_INTEGRATION,
    "alegra": FEATURE_ALEGRA_INTEGRATION,
    "worldoffice_cloud": FEATURE_WORLDOFFICE_INTEGRATION,
    "novasoft": FEATURE_NOVASOFT_INTEGRATION,
    "syscafe": FEATURE_SYSCAFE_INTEGRATION,
}


def is_enabled(name: str, default: bool = False) -> bool:
    return settings.FEATURE_FLAGS.get(name, default)


def is_provider_enabled(provider: object) -> bool:
    """Indica si el proveedor está habilitado sin acoplar config al dominio."""
    name = getattr(provider, "value", provider)
    flag = _PROVIDER_FLAGS.get(str(name))
    return is_enabled(flag) if flag else False


def enabled_features() -> dict[str, bool]:
    known = {
        FEATURE_DIAN_INTEGRATION,
        FEATURE_SIIGO_INTEGRATION,
        FEATURE_ALEGRA_INTEGRATION,
        FEATURE_WORLDOFFICE_INTEGRATION,
        FEATURE_NOVASOFT_INTEGRATION,
        FEATURE_SYSCAFE_INTEGRATION,
        FEATURE_LLM,
        FEATURE_MOCK_EXTERNAL_SERVICES,
    }
    return {
        name: settings.FEATURE_FLAGS.get(name, False)
        for name in sorted(known)
    }
