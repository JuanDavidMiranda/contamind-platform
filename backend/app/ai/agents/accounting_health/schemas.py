"""Contratos públicos del agente de salud contable, sin datos personales."""

from datetime import datetime
from enum import Enum
from uuid import UUID

from pydantic import Field

from app.providers.canonical import CanonicalModel


class AccountingHealthStatus(str, Enum):
    HEALTHY = "healthy"
    NEEDS_ATTENTION = "needs_attention"
    CRITICAL = "critical"


class AccountingHealthSeverity(str, Enum):
    CRITICAL = "critical"
    WARNING = "warning"
    INFO = "info"


class AccountingHealthConversationOutcome(str, Enum):
    ANSWERED = "answered"
    CLARIFICATION_NEEDED = "clarification_needed"
    OUT_OF_SCOPE = "out_of_scope"
    TEMPORARILY_UNAVAILABLE = "temporarily_unavailable"


class AccountingHealthMetrics(CanonicalModel):
    data_sources: int = Field(ge=0)
    active_data_sources: int = Field(ge=0)
    import_batches: int = Field(ge=0)
    accepted_import_rows: int = Field(ge=0)
    rejected_import_rows: int = Field(ge=0)
    parties: int = Field(ge=0)
    taxes: int = Field(ge=0)
    items: int = Field(ge=0)
    invoices: int = Field(ge=0)
    payments: int = Field(ge=0)
    journal_entries: int = Field(ge=0)


class AccountingHealthFinding(CanonicalModel):
    code: str = Field(pattern=r"^[A-Z][A-Z0-9_]{2,63}$")
    severity: AccountingHealthSeverity
    message: str = Field(min_length=1, max_length=500)
    evidence: dict[str, int] = Field(default_factory=dict)
    recommendation: str = Field(min_length=1, max_length=500)


class AccountingHealthSummary(CanonicalModel):
    status: AccountingHealthStatus
    finding_count: int = Field(ge=0)
    critical_count: int = Field(ge=0)
    warning_count: int = Field(ge=0)
    info_count: int = Field(ge=0)


class AccountingHealthReport(CanonicalModel):
    company_id: UUID
    generated_at: datetime
    overall_status: AccountingHealthStatus
    summary: AccountingHealthSummary
    metrics: AccountingHealthMetrics
    findings: tuple[AccountingHealthFinding, ...]


class AccountingHealthEvidence(CanonicalModel):
    source: str = Field(default="accounting_health_snapshot", max_length=64)
    finding_codes: tuple[str, ...] = ()
    metric_keys: tuple[str, ...] = ()


class AccountingHealthConversation(CanonicalModel):
    outcome: AccountingHealthConversationOutcome
    response: str = Field(min_length=1, max_length=4_000)
    evidence: tuple[AccountingHealthEvidence, ...] = ()
    suggested_questions: tuple[str, ...] = ()
    llm_used: bool = False
    llm_model: str | None = Field(default=None, max_length=128)