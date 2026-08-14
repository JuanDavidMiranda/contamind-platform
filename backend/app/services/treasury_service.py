"""Diagnóstico determinista de tesorería a partir de proyección y conciliación."""

from collections import defaultdict
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select
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
from app.models.bank_reconciliation import (
    BankAccountRecord,
    BankBalanceSnapshotRecord,
)


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
        balance_snapshot_metrics = self._balance_snapshot_metrics(company_id, analysis_date)
        metrics = self._metrics(
            cash_flow.metrics,
            reconciliation.metrics,
            balance_snapshot_metrics,
            analysis_date,
        )
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

    def _metrics(self, cash_flow, reconciliation, balance_snapshots, as_of: date) -> TreasuryMetrics:
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
            verified_balance_accounts=balance_snapshots["accounts"],
            bank_accounts_without_verified_balance=balance_snapshots["missing_accounts"],
            verified_balance_coverage=balance_snapshots["coverage"],
            verified_balance_cutoff_date=balance_snapshots["cutoff_date"],
            verified_bank_balances=balance_snapshots["balances"],
            imported_bank_transactions=reconciliation.imported_transactions,
            reconciled_bank_transactions=reconciliation.reconciled_transactions,
            pending_bank_transactions=reconciliation.pending_transactions,
            suggested_bank_transactions=reconciliation.suggested_matches,
            unmatched_bank_transactions=reconciliation.unmatched_transactions,
            ambiguous_bank_transactions=reconciliation.ambiguous_transactions,
            reconciliation_rate=reconciliation.reconciliation_rate,
        )

    def _balance_snapshot_metrics(self, company_id: UUID, as_of: date) -> dict[str, object]:
        active_accounts = tuple(
            self._db.scalars(
                select(BankAccountRecord).where(
                    BankAccountRecord.company_id == str(company_id),
                    BankAccountRecord.status == "active",
                )
            )
        )
        if not active_accounts:
            return {
                "accounts": 0,
                "missing_accounts": 0,
                "coverage": Decimal("0"),
                "cutoff_date": None,
                "balances": (),
            }
        latest_dates = (
            select(
                BankBalanceSnapshotRecord.bank_account_id.label("bank_account_id"),
                func.max(BankBalanceSnapshotRecord.as_of_date).label("as_of_date"),
            )
            .where(
                BankBalanceSnapshotRecord.company_id == str(company_id),
                BankBalanceSnapshotRecord.as_of_date <= as_of,
            )
            .group_by(BankBalanceSnapshotRecord.bank_account_id)
            .subquery()
        )
        snapshots = tuple(
            self._db.scalars(
                select(BankBalanceSnapshotRecord)
                .join(
                    latest_dates,
                    (BankBalanceSnapshotRecord.bank_account_id == latest_dates.c.bank_account_id)
                    & (BankBalanceSnapshotRecord.as_of_date == latest_dates.c.as_of_date),
                )
                .join(BankAccountRecord, BankAccountRecord.id == BankBalanceSnapshotRecord.bank_account_id)
                .where(BankAccountRecord.status == "active")
            )
        )
        snapshot_count = len(snapshots)
        account_count = len(active_accounts)
        coverage = (
            Decimal(snapshot_count * 100) / Decimal(account_count)
        ).quantize(_CENT)
        cutoff_dates = {snapshot.as_of_date for snapshot in snapshots}
        aligned = snapshot_count == account_count and len(cutoff_dates) == 1
        balances: defaultdict[str, Decimal] = defaultdict(lambda: Decimal("0"))
        if aligned:
            for snapshot in snapshots:
                balances[snapshot.currency_code] += Decimal(snapshot.balance)
        return {
            "accounts": snapshot_count,
            "missing_accounts": account_count - snapshot_count,
            "coverage": coverage,
            "cutoff_date": next(iter(cutoff_dates)) if aligned else None,
            "balances": self._amounts(balances) if aligned else (),
        }

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
        findings: list[TreasuryFinding] = []
        if metrics.verified_balance_cutoff_date is not None:
            findings.append(
                TreasuryFinding(
                    code="TREASURY_VERIFIED_BANK_BALANCE_AVAILABLE",
                    severity=TreasurySeverity.INFO,
                    message="Hay un corte bancario verificado que cubre todas las cuentas activas en la misma fecha.",
                    evidence={"accounts": metrics.verified_balance_accounts},
                    recommendation="Usa el saldo por moneda como punto de partida y contrástalo con vencimientos, recaudos y obligaciones antes de decidir pagos.",
                )
            )
        elif not metrics.verified_balance_accounts:
            findings.append(
                TreasuryFinding(
                    code="TREASURY_POSITION_REQUIRES_VERIFIED_BANK_BALANCE",
                    severity=TreasurySeverity.WARNING,
                    message="No hay un corte bancario verificado para conocer el saldo de las cuentas activas.",
                    evidence={"accounts": metrics.bank_accounts},
                    recommendation="Registra un corte de saldo por cada cuenta activa en Conciliación operativa.",
                )
            )
        elif metrics.bank_accounts_without_verified_balance:
            findings.append(
                TreasuryFinding(
                    code="TREASURY_VERIFIED_BANK_BALANCE_INCOMPLETE",
                    severity=TreasurySeverity.WARNING,
                    message="Falta un corte bancario verificado para una o más cuentas activas.",
                    evidence={"accounts_without_snapshot": metrics.bank_accounts_without_verified_balance},
                    recommendation="Completa el corte de todas las cuentas activas antes de sumar saldos por moneda.",
                )
            )
        else:
            findings.append(
                TreasuryFinding(
                    code="TREASURY_VERIFIED_BANK_BALANCE_CUTS_NOT_ALIGNED",
                    severity=TreasurySeverity.WARNING,
                    message="Los cortes bancarios verificados no corresponden a una misma fecha y no se pueden sumar como un saldo único.",
                    evidence={"accounts": metrics.verified_balance_accounts},
                    recommendation="Registra cortes de la misma fecha para todas las cuentas activas antes de interpretar una posición consolidada.",
                )
            )
        findings.append(
            TreasuryFinding(
                code="TREASURY_PAYMENT_DECISION_REQUIRES_HUMAN_REVIEW",
                severity=TreasurySeverity.INFO,
                message="Un saldo bancario verificado no confirma por sí solo que se pueda autorizar un pago.",
                evidence={"currencies": len(metrics.verified_bank_balances)},
                recommendation="Verifica obligaciones fuera del modelo, certeza de recaudo y autorizaciones internas antes de tomar una decisión.",
            )
        )
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
