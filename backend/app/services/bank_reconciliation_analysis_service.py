"""Diagnóstico agregado de cobertura de conciliación bancaria."""

from collections import defaultdict
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.ai.agents.bank_reconciliation.schemas import (
    BankReconciliationAmount,
    BankReconciliationFinding,
    BankReconciliationMetrics,
    BankReconciliationReport,
    BankReconciliationSeverity,
    BankReconciliationStatus,
    BankReconciliationSummary,
)
from app.models.bank_reconciliation import (
    BankAccountRecord,
    BankStatementImportRecord,
    BankTransactionRecord,
)


_CENT = Decimal("0.01")


class BankReconciliationAnalysisService:
    def __init__(self, db: Session) -> None:
        self._db = db

    def analyze(self, company_id: UUID) -> BankReconciliationReport:
        company_key = str(company_id)
        account_count = self._count(BankAccountRecord.id, BankAccountRecord.company_id, company_key)
        import_count = self._count(
            BankStatementImportRecord.id,
            BankStatementImportRecord.company_id,
            company_key,
        )
        transactions = tuple(
            self._db.scalars(
                select(BankTransactionRecord).where(
                    BankTransactionRecord.company_id == company_key
                )
            )
        )
        counts: defaultdict[str, int] = defaultdict(int)
        inflows: defaultdict[str, Decimal] = defaultdict(lambda: Decimal("0"))
        outflows: defaultdict[str, Decimal] = defaultdict(lambda: Decimal("0"))
        ambiguous = 0
        unmatched = 0
        for transaction in transactions:
            counts[transaction.status] += 1
            amount = Decimal(transaction.amount)
            if amount > 0:
                inflows[transaction.currency_code] += amount
            else:
                outflows[transaction.currency_code] += abs(amount)
            if transaction.status == "pending":
                if transaction.match_candidate_count > 1:
                    ambiguous += 1
                elif transaction.match_candidate_count == 0:
                    unmatched += 1
            elif transaction.status == "dismissed":
                unmatched += 1

        eligible = len(transactions) - counts["excluded"]
        rate = (
            (Decimal(counts["reconciled"]) * Decimal("100") / Decimal(eligible))
            if eligible
            else Decimal("0")
        ).quantize(_CENT)
        metrics = BankReconciliationMetrics(
            as_of_date=datetime.now(UTC).date(),
            bank_accounts=account_count,
            statement_imports=import_count,
            imported_transactions=len(transactions),
            pending_transactions=counts["pending"],
            suggested_matches=counts["suggested"],
            reconciled_transactions=counts["reconciled"],
            dismissed_transactions=counts["dismissed"],
            excluded_transactions=counts["excluded"],
            unmatched_transactions=unmatched,
            ambiguous_transactions=ambiguous,
            reconciliation_rate=rate,
            statement_inflows=self._amounts(inflows),
            statement_outflows=self._amounts(outflows),
        )
        findings = self._findings(metrics)
        summary = self._summary(findings)
        return BankReconciliationReport(
            company_id=company_id,
            generated_at=datetime.now(UTC),
            overall_status=summary.status,
            summary=summary,
            metrics=metrics,
            findings=tuple(findings),
        )

    def _count(self, identifier, company_column, company_id: str) -> int:
        return int(
            self._db.scalar(select(func.count(identifier)).where(company_column == company_id))
            or 0
        )

    @staticmethod
    def _amounts(values: dict[str, Decimal]) -> tuple[BankReconciliationAmount, ...]:
        return tuple(
            BankReconciliationAmount(
                currency_code=currency,
                amount=amount.quantize(_CENT),
            )
            for currency, amount in sorted(values.items())
            if amount
        )

    @staticmethod
    def _findings(
        metrics: BankReconciliationMetrics,
    ) -> list[BankReconciliationFinding]:
        findings: list[BankReconciliationFinding] = []
        if not metrics.bank_accounts:
            findings.append(
                BankReconciliationFinding(
                    code="NO_BANK_ACCOUNTS_CONFIGURED",
                    severity=BankReconciliationSeverity.INFO,
                    message="No hay cuentas bancarias configuradas para conciliar.",
                    evidence={"accounts": 0},
                    recommendation="Crea un alias de cuenta y carga un extracto CSV en la vista operativa.",
                )
            )
        elif not metrics.imported_transactions:
            findings.append(
                BankReconciliationFinding(
                    code="NO_BANK_TRANSACTIONS_IMPORTED",
                    severity=BankReconciliationSeverity.INFO,
                    message="Las cuentas configuradas todavía no tienen movimientos importados.",
                    evidence={"transactions": 0},
                    recommendation="Importa un extracto CSV sin números completos de cuenta en su contenido descriptivo.",
                )
            )
        if metrics.suggested_matches:
            findings.append(
                BankReconciliationFinding(
                    code="BANK_MATCHES_REQUIRE_HUMAN_REVIEW",
                    severity=BankReconciliationSeverity.WARNING,
                    message="Hay coincidencias exactas sugeridas que aún requieren confirmación humana.",
                    evidence={"transactions": metrics.suggested_matches},
                    recommendation="Revisa fecha, importe y moneda en Conciliación operativa antes de confirmar.",
                )
            )
        if metrics.ambiguous_transactions:
            findings.append(
                BankReconciliationFinding(
                    code="AMBIGUOUS_BANK_MATCHES",
                    severity=BankReconciliationSeverity.WARNING,
                    message="Hay movimientos con más de un pago contable posible.",
                    evidence={"transactions": metrics.ambiguous_transactions},
                    recommendation="Revisa el detalle operativo; el sistema no elige automáticamente entre coincidencias ambiguas.",
                )
            )
        if metrics.unmatched_transactions:
            findings.append(
                BankReconciliationFinding(
                    code="UNMATCHED_BANK_TRANSACTIONS",
                    severity=BankReconciliationSeverity.WARNING,
                    message="Hay movimientos bancarios sin un pago contable único asociado.",
                    evidence={"transactions": metrics.unmatched_transactions},
                    recommendation="Valida si falta registrar el pago, si la fecha difiere o si el movimiento debe excluirse.",
                )
            )
        return findings

    @staticmethod
    def _summary(
        findings: list[BankReconciliationFinding],
    ) -> BankReconciliationSummary:
        warning_count = sum(
            finding.severity is BankReconciliationSeverity.WARNING
            for finding in findings
        )
        info_count = sum(
            finding.severity is BankReconciliationSeverity.INFO for finding in findings
        )
        status = (
            BankReconciliationStatus.NEEDS_ATTENTION
            if warning_count
            else BankReconciliationStatus.HEALTHY
        )
        return BankReconciliationSummary(
            status=status,
            finding_count=len(findings),
            warning_count=warning_count,
            info_count=info_count,
        )
