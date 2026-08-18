"""Contratos agregados para la preparación de información exógena."""

from datetime import datetime
from decimal import Decimal
from enum import Enum
from uuid import UUID

from pydantic import Field

from app.providers.canonical import CanonicalModel


class ExogenousInformationStatus(str, Enum):
    HEALTHY = "healthy"
    NEEDS_ATTENTION = "needs_attention"
    CRITICAL = "critical"


class ExogenousInformationSeverity(str, Enum):
    CRITICAL = "critical"
    WARNING = "warning"
    INFO = "info"


class ExogenousInformationMetrics(CanonicalModel):
    tax_year: int = Field(ge=2000, le=2100)
    registered_parties: int = Field(ge=0)
    parties_with_complete_identification: int = Field(ge=0)
    parties_missing_document_type: int = Field(ge=0)
    parties_missing_document_number: int = Field(ge=0)
    parties_missing_city: int = Field(ge=0)
    parties_missing_address: int = Field(ge=0)
    party_identification_coverage: Decimal = Field(ge=0, le=100)
    invoices_in_tax_year: int = Field(ge=0)
    invoices_missing_number: int = Field(ge=0)
    invoices_missing_counterparty: int = Field(ge=0)
    invoices_with_total_mismatch: int = Field(ge=0)
    payments_in_tax_year: int = Field(ge=0)
    payments_without_invoice: int = Field(ge=0)


class ExogenousInformationFinding(CanonicalModel):
    code: str = Field(pattern=r"^[A-Z][A-Z0-9_]{2,63}$")
    severity: ExogenousInformationSeverity
    message: str = Field(min_length=1, max_length=500)
    evidence: dict[str, int] = Field(default_factory=dict)
    recommendation: str = Field(min_length=1, max_length=500)


class ExogenousInformationSummary(CanonicalModel):
    status: ExogenousInformationStatus
    finding_count: int = Field(ge=0)
    critical_count: int = Field(ge=0)
    warning_count: int = Field(ge=0)
    info_count: int = Field(ge=0)


class ExogenousInformationReport(CanonicalModel):
    company_id: UUID
    generated_at: datetime
    overall_status: ExogenousInformationStatus
    summary: ExogenousInformationSummary
    metrics: ExogenousInformationMetrics
    findings: tuple[ExogenousInformationFinding, ...]


class ExogenousInformationConversation(CanonicalModel):
    outcome: str = Field(pattern=r"^(?:answered|clarification_needed|out_of_scope)$")
    response: str = Field(min_length=1, max_length=4_000)
    suggested_questions: tuple[str, ...] = ()
    llm_used: bool = False
    llm_model: str | None = None
