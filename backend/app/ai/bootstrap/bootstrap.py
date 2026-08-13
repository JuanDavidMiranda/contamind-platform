import logging

from app.ai.agents.accounting_health import AccountingHealthAgent
from app.ai.agents.bank_reconciliation import BankReconciliationAgent
from app.ai.agents.cash_flow import CashFlowAgent
from app.ai.agents.receivables import ReceivablesAgent
from app.ai.agents.payables import PayablesAgent
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
    agent_registry.register(ReceivablesAgent())
    logger.info("agent registered", extra={"agent": "receivables"})
    agent_registry.register(PayablesAgent())
    logger.info("agent registered", extra={"agent": "payables"})
    agent_registry.register(CashFlowAgent())
    logger.info("agent registered", extra={"agent": "cash_flow"})
    agent_registry.register(BankReconciliationAgent())
    logger.info("agent registered", extra={"agent": "bank_reconciliation"})
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
