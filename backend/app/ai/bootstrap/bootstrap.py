import logging

from app.ai.agents.accounting_health import AccountingHealthAgent
from app.ai.registry import registry as agent_registry
from app.ai.tools.registry import registry

from app.ai.tools.consultar_obligaciones import ConsultarObligacionesTool
from app.config.features import (
    FEATURE_MOCK_EXTERNAL_SERVICES,
    is_enabled,
)

logger = logging.getLogger("contamind.bootstrap")


def bootstrap() -> None:
    agent_registry.register(AccountingHealthAgent())
    logger.info("agent registered", extra={"agent": "accounting_health"})
    if is_enabled(FEATURE_MOCK_EXTERNAL_SERVICES, default=True):
        registry.register(ConsultarObligacionesTool())
        logger.info(
            "tool registrada (MOCK)",
            extra={"tool": "Consultar obligaciones", "mock": True},
        )
    else:
        logger.info(
            "tool de obligaciones no registrada: mocks deshabilitados",
            extra={"tool": "Consultar obligaciones"},
        )
