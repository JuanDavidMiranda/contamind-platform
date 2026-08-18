"""Contratos agregados para el diagnóstico de facturación electrónica."""

from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from uuid import UUID

from pydantic import Field

from app.providers.canonical import CanonicalModel


class ElectronicInvoicingStatus(str, Enum):
    HEALTHY = "healthy"
    NEEDS_ATTENTION = "needs_attention"
    CRITICAL = "critical"


class ElectronicInvoicingSeverity(str, Enum):
    CRITICAL = "critical"
    WARNING = "warning"
    INFO = "info"


class ElectronicInvoicingMetrics(CanonicalModel):
    as_of_date: date = Field(default_factory=date.today)
    sales_invoices: int = Field(ge=0)
    electronic_status_recorded: int = Field(ge=0)
    accepted_electronic_invoices: int = Field(ge=0)
    pending_electronic_invoices: int = Field(ge=0)
    rejected_electronic_invoices: int = Field(ge=0)
    invoices_without_electronic_status: int = Field(ge=0)
    invoices_without_electronic_reference: int = Field(ge=0)
    invoices_missing_number: int = Field(ge=0)
    invoices_without_recipient: int = Field(ge=0)
    invoices_with_total_mismatch: int = Field(ge=0)
    future_dated_sales_invoices: int = Field(ge=0)
    electronic_status_coverage: Decimal = Field(ge=0, le=100)


class ElectronicInvoicingFinding(CanonicalModel):
    code: str = Field(pattern=r"^[A-Z][A-Z0-9_]{2,63}$")
    severity: ElectronicInvoicingSeverity
    message: str = Field(min_length=1, max_length=500)
    evidence: dict[str, int] = Field(default_factory=dict)
    recommendation: str = Field(min_length=1, max_length=500)


class ElectronicInvoicingSummary(CanonicalModel):
    status: ElectronicInvoicingStatus
    finding_count: int = Field(ge=0)
    critical_count: int = Field(ge=0)
    warning_count: int = Field(ge=0)
    info_count: int = Field(ge=0)


class ElectronicInvoicingReport(CanonicalModel):
    company_id: UUID
    generated_at: datetime
    overall_status: ElectronicInvoicingStatus
    summary: ElectronicInvoicingSummary
    metrics: ElectronicInvoicingMetrics
    findings: tuple[ElectronicInvoicingFinding, ...]


class ElectronicInvoicingConversation(CanonicalModel):
    outcome: str = Field(pattern=r"^(?:answered|clarification_needed|out_of_scope)$")
    response: str = Field(min_length=1, max_length=4_000)
    suggested_questions: tuple[str, ...] = ()
    llm_used: bool = False
    llm_model: str | None = None
