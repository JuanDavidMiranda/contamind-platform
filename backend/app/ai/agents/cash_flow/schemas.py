"""Contratos agregados del agente de flujo de caja."""

from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from uuid import UUID

from pydantic import Field

from app.providers.canonical import CanonicalModel


class CashFlowStatus(str, Enum):
    HEALTHY = "healthy"
    NEEDS_ATTENTION = "needs_attention"


class CashFlowSeverity(str, Enum):
    WARNING = "warning"
    INFO = "info"


class CashFlowAmount(CanonicalModel):
    currency_code: str = Field(pattern=r"^[A-Z]{3}$")
    amount: Decimal


class CashFlowPeriod(CanonicalModel):
    """Movimientos abiertos cuyo vencimiento cae dentro de un período."""

    key: str = Field(
        pattern=(
            r"^(?:overdue|due_today|next_7_days|days_8_30|"
            r"days_31_60|days_61_90|beyond_90)$"
        )
    )
    start_date: date | None = None
    end_date: date | None = None
    receivable_invoices: int = Field(ge=0)
    payable_invoices: int = Field(ge=0)
    projected_inflows: tuple[CashFlowAmount, ...] = ()
    projected_outflows: tuple[CashFlowAmount, ...] = ()
    net_movements: tuple[CashFlowAmount, ...] = ()


class CashFlowMetrics(CanonicalModel):
    as_of_date: date = Field(default_factory=date.today)
    horizon_days: int = Field(default=90, ge=1, le=365)
    open_receivables: int = Field(ge=0)
    open_payables: int = Field(ge=0)
    scheduled_receivables: int = Field(ge=0)
    scheduled_payables: int = Field(ge=0)
    receivables_missing_due_date: int = Field(ge=0)
    payables_missing_due_date: int = Field(ge=0)
    currencies: int = Field(ge=0)
    projected_inflows_90d: tuple[CashFlowAmount, ...] = ()
    projected_outflows_90d: tuple[CashFlowAmount, ...] = ()
    net_movements_90d: tuple[CashFlowAmount, ...] = ()
    cash_flow_periods: tuple[CashFlowPeriod, ...] = ()


class CashFlowFinding(CanonicalModel):
    code: str = Field(pattern=r"^[A-Z][A-Z0-9_]{2,63}$")
    severity: CashFlowSeverity
    message: str = Field(min_length=1, max_length=500)
    evidence: dict[str, int] = Field(default_factory=dict)
    recommendation: str = Field(min_length=1, max_length=500)


class CashFlowSummary(CanonicalModel):
    status: CashFlowStatus
    finding_count: int = Field(ge=0)
    critical_count: int = Field(default=0, ge=0)
    warning_count: int = Field(ge=0)
    info_count: int = Field(ge=0)


class CashFlowReport(CanonicalModel):
    company_id: UUID
    generated_at: datetime
    overall_status: CashFlowStatus
    summary: CashFlowSummary
    metrics: CashFlowMetrics
    findings: tuple[CashFlowFinding, ...]


class CashFlowConversation(CanonicalModel):
    outcome: str = Field(
        pattern=r"^(?:answered|clarification_needed|out_of_scope)$"
    )
    response: str = Field(min_length=1, max_length=4_000)
    suggested_questions: tuple[str, ...] = ()
    llm_used: bool = False
    llm_model: str | None = None
