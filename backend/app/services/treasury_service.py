"""Diagnóstico determinista de tesorería a partir de proyección y conciliación."""

from collections import defaultdict
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy.orm import Session

from app.ai.agents.treasury.schemas import (
    TreasuryAmount,
    TreasuryFinding,
    TreasuryMetrics,
    TreasuryReport,
    TreasurySeverity,
    TreasuryStatus,
    TreasurySummary,
)
from app.services.bank_reconciliation_analysis_service import (
    BankReconciliationAnalysisService,
)
from app.services.cash_flow_service import CashFlowService


_CENT = Decimal("0.01")
_THIRTY_DAY_PERIODS = {"overdue", "due_today", "next_7_days", "days_8_30"}


class TreasuryService:
    """Reúne señales de caja sin inferir la disponibilidad bancaria real."""

    def __init__(self, db: Session) -> None:
        self._db = db

    def analyze(
        self,
        company_id: UUID,
        *,
        as_of: date | None = None,
    ) -> TreasuryReport:
        analysis_date = as_of or datetime.now(UTC).date()
        cash_flow = CashFlowService(self._db).analyze(company_id, as_of=analysis_date)
        reconciliation = BankReconciliationAnalysisService(self._db).analyze(company_id)
        metrics = self._metrics(cash_flow.metrics, reconciliation.metrics, analysis_date)
        findings = self._findings(metrics)
        summary = self._summary(findings)
        return TreasuryReport(
            company_id=company_id,
            generated_at=datetime.now(UTC),
            overall_status=summary.status,
            summary=summary,
            metrics=metrics,
            findings=tuple(findings),
        )

    def _metrics(self, cash_flow, reconciliation, as_of: date) -> TreasuryMetrics:
        inflows: defaultdict[str, Decimal] = defaultdict(lambda: Decimal("0"))
        outflows: defaultdict[str, Decimal] = defaultdict(lambda: Decimal("0"))
        overdue_receivables = 0
        for period in cash_flow.cash_flow_periods:
            if period.key not in _THIRTY_DAY_PERIODS:
                continue
            if period.key == "overdue":
                overdue_receivables = period.receivable_invoices
            for amount in period.projected_inflows:
                inflows[amount.currency_code] += amount.amount
            for amount in period.projected_outflows:
                outflows[amount.currency_code] += amount.amount

        return TreasuryMetrics(
            as_of_date=as_of,
            projected_inflows_30d=self._amounts(inflows),
            projected_outflows_30d=self._amounts(outflows),
            net_projected_movements_30d=self._net_amounts(inflows, outflows),
            overdue_receivable_invoices=overdue_receivables,
            receivables_missing_due_date=cash_flow.receivables_missing_due_date,
            payables_missing_due_date=cash_flow.payables_missing_due_date,
            bank_accounts=reconciliation.bank_accounts,
            imported_bank_transactions=reconciliation.imported_transactions,
            reconciled_bank_transactions=reconciliation.reconciled_transactions,
            pending_bank_transactions=reconciliation.pending_transactions,
            suggested_bank_transactions=reconciliation.suggested_matches,
            unmatched_bank_transactions=reconciliation.unmatched_transactions,
            ambiguous_bank_transactions=reconciliation.ambiguous_transactions,
            reconciliation_rate=reconciliation.reconciliation_rate,
        )

    @staticmethod
    def _amounts(values: dict[str, Decimal]) -> tuple[TreasuryAmount, ...]:
        return tuple(
            TreasuryAmount(currency_code=currency, amount=amount.quantize(_CENT))
            for currency, amount in sorted(values.items())
            if amount
        )

    @classmethod
    def _net_amounts(
        cls,
        inflows: dict[str, Decimal],
        outflows: dict[str, Decimal],
    ) -> tuple[TreasuryAmount, ...]:
        return tuple(
            TreasuryAmount(
                currency_code=currency,
                amount=(inflows.get(currency, Decimal("0")) - outflows.get(currency, Decimal("0"))).quantize(_CENT),
            )
            for currency in sorted(set(inflows) | set(outflows))
        )

    @staticmethod
    def _findings(metrics: TreasuryMetrics) -> list[TreasuryFinding]:
        findings = [
            TreasuryFinding(
                code="TREASURY_POSITION_REQUIRES_VERIFIED_BANK_BALANCE",
                severity=TreasurySeverity.INFO,
                message="El reporte no determina disponibilidad real porque no recibe un saldo bancario verificado ni todas las obligaciones fuera del modelo.",
                evidence={"bank_accounts": metrics.bank_accounts},
                recommendation="Contrasta este diagnóstico con el saldo bancario verificado antes de autorizar pagos o financiación.",
            )
        ]
        if not metrics.bank_accounts or not metrics.imported_bank_transactions:
            findings.append(
                TreasuryFinding(
                    code="TREASURY_BANK_DATA_UNAVAILABLE",
                    severity=TreasurySeverity.WARNING,
                    message="No hay movimientos bancarios importados suficientes para contrastar la proyección con la conciliación.",
                    evidence={
                        "bank_accounts": metrics.bank_accounts,
                        "imported_transactions": metrics.imported_bank_transactions,
                    },
                    recommendation="Configura un alias de cuenta e importa un extracto CSV en Conciliación operativa.",
                )
            )
        review_count = (
            metrics.pending_bank_transactions
            + metrics.suggested_bank_transactions
            + metrics.unmatched_bank_transactions
            + metrics.ambiguous_bank_transactions
        )
        if review_count:
            findings.append(
                TreasuryFinding(
                    code="TREASURY_RECONCILIATION_REQUIRES_REVIEW",
                    severity=TreasurySeverity.WARNING,
                    message="La conciliación aún tiene movimientos por revisar, por lo que la señal bancaria no está completamente confirmada.",
                    evidence={
                        "pending": metrics.pending_bank_transactions,
                        "suggested": metrics.suggested_bank_transactions,
                        "unmatched": metrics.unmatched_bank_transactions,
                        "ambiguous": metrics.ambiguous_bank_transactions,
                    },
                    recommendation="Revisa las coincidencias y diferencias en Conciliación operativa antes de usar esa evidencia para decisiones de tesorería.",
                )
            )
        missing_dates = (
            metrics.receivables_missing_due_date
            + metrics.payables_missing_due_date
        )
        if missing_dates:
            findings.append(
                TreasuryFinding(
                    code="TREASURY_PROJECTED_MOVEMENTS_MISSING_DUE_DATE",
                    severity=TreasurySeverity.WARNING,
                    message="Hay facturas abiertas sin vencimiento y no entran en el horizonte de tesorería.",
                    evidence={
                        "receivables": metrics.receivables_missing_due_date,
                        "payables": metrics.payables_missing_due_date,
                    },
                    recommendation="Completa los vencimientos de cartera y cuentas por pagar antes de priorizar obligaciones.",
                )
            )
        negative_currencies = sum(
            amount.amount < 0 for amount in metrics.net_projected_movements_30d
        )
        if negative_currencies:
            findings.append(
                TreasuryFinding(
                    code="TREASURY_NEGATIVE_PROJECTED_NET_30D",
                    severity=TreasurySeverity.WARNING,
                    message="En una o más monedas, las salidas abiertas de los próximos treinta días superan las entradas proyectadas.",
                    evidence={"currencies": negative_currencies},
                    recommendation="Revisa vencimientos, certeza de recaudo y saldo bancario verificado por cada moneda antes de decidir pagos.",
                )
            )
        if metrics.overdue_receivable_invoices:
            findings.append(
                TreasuryFinding(
                    code="TREASURY_OVERDUE_RECEIVABLES_ARE_UNCERTAIN",
                    severity=TreasurySeverity.INFO,
                    message="La proyección incluye cartera vencida como entrada pendiente, no como efectivo confirmado.",
                    evidence={"invoices": metrics.overdue_receivable_invoices},
                    recommendation="Confirma el recaudo y actualiza los pagos antes de considerar esas entradas para tesorería.",
                )
            )
        return findings

    @staticmethod
    def _summary(findings: list[TreasuryFinding]) -> TreasurySummary:
        warning_count = sum(
            finding.severity is TreasurySeverity.WARNING for finding in findings
        )
        info_count = sum(
            finding.severity is TreasurySeverity.INFO for finding in findings
        )
        return TreasurySummary(
            status=(TreasuryStatus.NEEDS_ATTENTION if warning_count else TreasuryStatus.HEALTHY),
            finding_count=len(findings),
            warning_count=warning_count,
            info_count=info_count,
        )
