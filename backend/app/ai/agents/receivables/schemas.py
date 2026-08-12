"""Contratos públicos del agente de cartera, sin datos individuales."""

from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from uuid import UUID

from pydantic import Field

from app.providers.canonical import CanonicalModel


class ReceivablesStatus(str, Enum):
    HEALTHY = "healthy"
    NEEDS_ATTENTION = "needs_attention"
    CRITICAL = "critical"


class ReceivablesSeverity(str, Enum):
    CRITICAL = "critical"
    WARNING = "warning"
    INFO = "info"


class ReceivablesConversationOutcome(str, Enum):
    ANSWERED = "answered"
    CLARIFICATION_NEEDED = "clarification_needed"
    OUT_OF_SCOPE = "out_of_scope"
    TEMPORARILY_UNAVAILABLE = "temporarily_unavailable"


class ReceivablesBalance(CanonicalModel):
    currency_code: str = Field(pattern=r"^[A-Z]{3}$")
    amount: Decimal = Field(ge=0)


class ReceivablesAgingBucket(CanonicalModel):
    """Saldo abierto clasificado desde el vencimiento, separado por moneda."""

    key: str = Field(pattern=r"^(?:not_due|due_today|overdue_1_30|overdue_31_60|overdue_61_90|overdue_91_plus|missing_due_date)$")
    invoices: int = Field(ge=0)
    outstanding_balances: tuple[ReceivablesBalance, ...] = ()


class ReceivablesMetrics(CanonicalModel):
    as_of_date: date = Field(default_factory=date.today)
    sales_invoices: int = Field(ge=0)
    open_sales_invoices: int = Field(ge=0)
    unpaid_sales_invoices: int = Field(ge=0)
    partially_paid_sales_invoices: int = Field(ge=0)
    overpaid_sales_invoices: int = Field(ge=0)
    payments_with_currency_mismatch: int = Field(ge=0)
    sales_invoices_missing_due_date: int = Field(default=0, ge=0)
    due_today_sales_invoices: int = Field(default=0, ge=0)
    overdue_sales_invoices: int = Field(default=0, ge=0)
    seriously_overdue_sales_invoices: int = Field(default=0, ge=0)
    pending_collection_followups: int = Field(default=0, ge=0)
    open_payment_promises: int = Field(default=0, ge=0)
    broken_payment_promises: int = Field(default=0, ge=0)
    settled_sales_invoices: int = Field(default=0, ge=0)
    average_days_to_collect: Decimal | None = Field(default=None, ge=0)
    outstanding_balances: tuple[ReceivablesBalance, ...] = ()
    aging_buckets: tuple[ReceivablesAgingBucket, ...] = ()


class ReceivablesFinding(CanonicalModel):
    code: str = Field(pattern=r"^[A-Z][A-Z0-9_]{2,63}$")
    severity: ReceivablesSeverity
    message: str = Field(min_length=1, max_length=500)
    evidence: dict[str, int] = Field(default_factory=dict)
    recommendation: str = Field(min_length=1, max_length=500)


class ReceivablesSummary(CanonicalModel):
    status: ReceivablesStatus
    finding_count: int = Field(ge=0)
    critical_count: int = Field(ge=0)
    warning_count: int = Field(ge=0)
    info_count: int = Field(ge=0)


class ReceivablesReport(CanonicalModel):
    company_id: UUID
    generated_at: datetime
    overall_status: ReceivablesStatus
    summary: ReceivablesSummary
    metrics: ReceivablesMetrics
    findings: tuple[ReceivablesFinding, ...]


class ReceivablesEvidence(CanonicalModel):
    source: str = Field(default="receivables_snapshot", max_length=64)
    finding_codes: tuple[str, ...] = ()
    metric_keys: tuple[str, ...] = ()


class ReceivablesConversation(CanonicalModel):
    outcome: ReceivablesConversationOutcome
    response: str = Field(min_length=1, max_length=4_000)
    evidence: tuple[ReceivablesEvidence, ...] = ()
    suggested_questions: tuple[str, ...] = ()
    llm_used: bool = False
    llm_model: str | None = Field(default=None, max_length=128)
