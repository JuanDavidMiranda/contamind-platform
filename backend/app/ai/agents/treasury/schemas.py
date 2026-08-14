"""Contratos agregados del agente de tesorería."""

from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from uuid import UUID

from pydantic import Field

from app.providers.canonical import CanonicalModel


class TreasuryStatus(str, Enum):
    HEALTHY = "healthy"
    NEEDS_ATTENTION = "needs_attention"


class TreasurySeverity(str, Enum):
    WARNING = "warning"
    INFO = "info"


class TreasuryAmount(CanonicalModel):
    currency_code: str = Field(pattern=r"^[A-Z]{3}$")
    amount: Decimal


class TreasuryMetrics(CanonicalModel):
    """Señales agregadas de proyección, conciliación y cortes bancarios."""

    as_of_date: date = Field(default_factory=date.today)
    horizon_days: int = Field(default=30, ge=1, le=365)
    projected_inflows_30d: tuple[TreasuryAmount, ...] = ()
    projected_outflows_30d: tuple[TreasuryAmount, ...] = ()
    net_projected_movements_30d: tuple[TreasuryAmount, ...] = ()
    overdue_receivable_invoices: int = Field(ge=0)
    receivables_missing_due_date: int = Field(ge=0)
    payables_missing_due_date: int = Field(ge=0)
    bank_accounts: int = Field(ge=0)
    verified_balance_accounts: int = Field(ge=0)
    bank_accounts_without_verified_balance: int = Field(ge=0)
    verified_balance_coverage: Decimal = Field(ge=0, le=100)
    verified_balance_cutoff_date: date | None = None
    verified_bank_balances: tuple[TreasuryAmount, ...] = ()
    imported_bank_transactions: int = Field(ge=0)
    reconciled_bank_transactions: int = Field(ge=0)
    pending_bank_transactions: int = Field(ge=0)
    suggested_bank_transactions: int = Field(ge=0)
    unmatched_bank_transactions: int = Field(ge=0)
    ambiguous_bank_transactions: int = Field(ge=0)
    reconciliation_rate: Decimal = Field(ge=0, le=100)


class TreasuryFinding(CanonicalModel):
    code: str = Field(pattern=r"^[A-Z][A-Z0-9_]{2,63}$")
    severity: TreasurySeverity
    message: str = Field(min_length=1, max_length=500)
    evidence: dict[str, int] = Field(default_factory=dict)
    recommendation: str = Field(min_length=1, max_length=500)


class TreasurySummary(CanonicalModel):
    status: TreasuryStatus
    finding_count: int = Field(ge=0)
    critical_count: int = Field(default=0, ge=0)
    warning_count: int = Field(ge=0)
    info_count: int = Field(ge=0)


class TreasuryReport(CanonicalModel):
    company_id: UUID
    generated_at: datetime
    overall_status: TreasuryStatus
    summary: TreasurySummary
    metrics: TreasuryMetrics
    findings: tuple[TreasuryFinding, ...]


class TreasuryConversation(CanonicalModel):
    outcome: str = Field(pattern=r"^(?:answered|clarification_needed|out_of_scope)$")
    response: str = Field(min_length=1, max_length=4_000)
    suggested_questions: tuple[str, ...] = ()
    llm_used: bool = False
    llm_model: str | None = None
