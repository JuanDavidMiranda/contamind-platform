from app.config.settings import settings

FEATURE_DIAN_INTEGRATION = "DIAN_INTEGRATION_ENABLED"
FEATURE_SIIGO_INTEGRATION = "SIIGO_INTEGRATION_ENABLED"
FEATURE_LLM = "LLM_ENABLED"
FEATURE_MOCK_EXTERNAL_SERVICES = "MOCK_EXTERNAL_SERVICES"


def is_enabled(name: str, default: bool = False) -> bool:
    return settings.FEATURE_FLAGS.get(name, default)


def enabled_features() -> dict[str, bool]:
    known = {
        FEATURE_DIAN_INTEGRATION,
        FEATURE_SIIGO_INTEGRATION,
        FEATURE_LLM,
        FEATURE_MOCK_EXTERNAL_SERVICES,
    }
    return {
        name: settings.FEATURE_FLAGS.get(name, False)
        for name in sorted(known)
    }
