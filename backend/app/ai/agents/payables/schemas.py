"""Contratos agregados del agente de cuentas por pagar."""

from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from uuid import UUID

from pydantic import Field

from app.providers.canonical import CanonicalModel


class PayablesStatus(str, Enum):
    HEALTHY = "healthy"
    NEEDS_ATTENTION = "needs_attention"
    CRITICAL = "critical"


class PayablesSeverity(str, Enum):
    CRITICAL = "critical"
    WARNING = "warning"
    INFO = "info"


class PayablesBalance(CanonicalModel):
    currency_code: str = Field(pattern=r"^[A-Z]{3}$")
    amount: Decimal = Field(ge=0)


class PayablesAgingBucket(CanonicalModel):
    key: str = Field(pattern=r"^(?:not_due|due_today|overdue_1_30|overdue_31_60|overdue_61_90|overdue_91_plus|missing_due_date)$")
    invoices: int = Field(ge=0)
    outstanding_balances: tuple[PayablesBalance, ...] = ()


class PayablesMetrics(CanonicalModel):
    as_of_date: date = Field(default_factory=date.today)
    purchase_invoices: int = Field(ge=0)
    open_purchase_invoices: int = Field(ge=0)
    unpaid_purchase_invoices: int = Field(ge=0)
    partially_paid_purchase_invoices: int = Field(ge=0)
    overpaid_purchase_invoices: int = Field(ge=0)
    payments_with_currency_mismatch: int = Field(ge=0)
    purchase_invoices_missing_due_date: int = Field(ge=0)
    due_today_purchase_invoices: int = Field(ge=0)
    overdue_purchase_invoices: int = Field(ge=0)
    seriously_overdue_purchase_invoices: int = Field(ge=0)
    settled_purchase_invoices: int = Field(ge=0)
    average_days_to_pay: Decimal | None = Field(default=None, ge=0)
    outstanding_balances: tuple[PayablesBalance, ...] = ()
    aging_buckets: tuple[PayablesAgingBucket, ...] = ()


class PayablesFinding(CanonicalModel):
    code: str = Field(pattern=r"^[A-Z][A-Z0-9_]{2,63}$")
    severity: PayablesSeverity
    message: str = Field(min_length=1, max_length=500)
    evidence: dict[str, int] = Field(default_factory=dict)
    recommendation: str = Field(min_length=1, max_length=500)


class PayablesSummary(CanonicalModel):
    status: PayablesStatus
    finding_count: int = Field(ge=0)
    critical_count: int = Field(ge=0)
    warning_count: int = Field(ge=0)
    info_count: int = Field(ge=0)


class PayablesReport(CanonicalModel):
    company_id: UUID
    generated_at: datetime
    overall_status: PayablesStatus
    summary: PayablesSummary
    metrics: PayablesMetrics
    findings: tuple[PayablesFinding, ...]


class PayablesConversation(CanonicalModel):
    outcome: str = Field(pattern=r"^(?:answered|clarification_needed|out_of_scope)$")
    response: str = Field(min_length=1, max_length=4_000)
    suggested_questions: tuple[str, ...] = ()
    llm_used: bool = False
    llm_model: str | None = None
