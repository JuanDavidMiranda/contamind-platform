"""Contratos agregados del agente de conciliación bancaria."""

from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from uuid import UUID

from pydantic import Field

from app.providers.canonical import CanonicalModel


class BankReconciliationStatus(str, Enum):
    HEALTHY = "healthy"
    NEEDS_ATTENTION = "needs_attention"


class BankReconciliationSeverity(str, Enum):
    WARNING = "warning"
    INFO = "info"


class BankReconciliationAmount(CanonicalModel):
    currency_code: str = Field(pattern=r"^[A-Z]{3}$")
    amount: Decimal = Field(ge=0)


class BankReconciliationMetrics(CanonicalModel):
    as_of_date: date = Field(default_factory=date.today)
    bank_accounts: int = Field(ge=0)
    statement_imports: int = Field(ge=0)
    imported_transactions: int = Field(ge=0)
    pending_transactions: int = Field(ge=0)
    suggested_matches: int = Field(ge=0)
    reconciled_transactions: int = Field(ge=0)
    dismissed_transactions: int = Field(ge=0)
    excluded_transactions: int = Field(ge=0)
    unmatched_transactions: int = Field(ge=0)
    ambiguous_transactions: int = Field(ge=0)
    reconciliation_rate: Decimal = Field(ge=0, le=100)
    statement_inflows: tuple[BankReconciliationAmount, ...] = ()
    statement_outflows: tuple[BankReconciliationAmount, ...] = ()


class BankReconciliationFinding(CanonicalModel):
    code: str = Field(pattern=r"^[A-Z][A-Z0-9_]{2,63}$")
    severity: BankReconciliationSeverity
    message: str = Field(min_length=1, max_length=500)
    evidence: dict[str, int] = Field(default_factory=dict)
    recommendation: str = Field(min_length=1, max_length=500)


class BankReconciliationSummary(CanonicalModel):
    status: BankReconciliationStatus
    finding_count: int = Field(ge=0)
    critical_count: int = Field(default=0, ge=0)
    warning_count: int = Field(ge=0)
    info_count: int = Field(ge=0)


class BankReconciliationReport(CanonicalModel):
    company_id: UUID
    generated_at: datetime
    overall_status: BankReconciliationStatus
    summary: BankReconciliationSummary
    metrics: BankReconciliationMetrics
    findings: tuple[BankReconciliationFinding, ...]


class BankReconciliationConversation(CanonicalModel):
    outcome: str = Field(
        pattern=r"^(?:answered|clarification_needed|out_of_scope)$"
    )
    response: str = Field(min_length=1, max_length=4_000)
    suggested_questions: tuple[str, ...] = ()
    llm_used: bool = False
    llm_model: str | None = None
