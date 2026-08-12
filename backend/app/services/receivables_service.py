"""Análisis determinista y de sólo lectura de cartera de ventas por empresa."""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, date, datetime
from decimal import Decimal, ROUND_HALF_UP
from uuid import UUID

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from app.ai.agents.receivables.schemas import (
    ReceivablesAgingBucket,
    ReceivablesBalance,
    ReceivablesFinding,
    ReceivablesMetrics,
    ReceivablesReport,
    ReceivablesSeverity,
    ReceivablesStatus,
    ReceivablesSummary,
)
from app.models.accounting import InvoiceRecord, PaymentRecord
from app.models.collection_followup import CollectionFollowUpRecord
from app.services.collection_followup_service import CollectionFollowUpStatus


_CENT = Decimal("0.01")
_AGING_KEYS = (
    "not_due",
    "due_today",
    "overdue_1_30",
    "overdue_31_60",
    "overdue_61_90",
    "overdue_91_plus",
    "missing_due_date",
)


class ReceivablesService:
    """Calcula saldos y antigüedad por moneda sin revelar facturas ni terceros."""

    def __init__(self, db: Session) -> None:
        self._db = db

    def analyze(
        self,
        company_id: UUID,
        *,
        as_of: date | None = None,
    ) -> ReceivablesReport:
        analysis_date = as_of or datetime.now(UTC).date()
        company_key = str(company_id)
        rows = self._sale_invoice_balances(company_key)
        metrics = self._metrics(rows, company_key, analysis_date)
        findings = self._findings(metrics, company_key)
        summary = self._summary(findings)
        return ReceivablesReport(
            company_id=company_id,
            generated_at=datetime.now(UTC),
            overall_status=summary.status,
            summary=summary,
            metrics=metrics,
            findings=tuple(findings),
        )

    def _sale_invoice_balances(self, company_id: str):
        paid_amount = func.coalesce(func.sum(PaymentRecord.amount), Decimal("0"))
        latest_payment_date = func.max(PaymentRecord.payment_date)
        return self._db.execute(
            select(
                InvoiceRecord.id,
                InvoiceRecord.issue_date,
                InvoiceRecord.due_date,
                InvoiceRecord.currency_code,
                InvoiceRecord.total,
                InvoiceRecord.recipient_party_id,
                paid_amount.label("paid_amount"),
                latest_payment_date.label("latest_payment_date"),
            )
            .outerjoin(PaymentRecord, self._matching_payment_join())
            .where(
                InvoiceRecord.company_id == company_id,
                InvoiceRecord.invoice_type == "sale",
            )
            .group_by(
                InvoiceRecord.id,
                InvoiceRecord.issue_date,
                InvoiceRecord.due_date,
                InvoiceRecord.currency_code,
                InvoiceRecord.total,
                InvoiceRecord.recipient_party_id,
            )
        ).all()

    @staticmethod
    def _matching_payment_join():
        return and_(
            PaymentRecord.invoice_id == InvoiceRecord.id,
            PaymentRecord.company_id == InvoiceRecord.company_id,
            PaymentRecord.currency_code == InvoiceRecord.currency_code,
        )

    def _metrics(self, rows, company_id: str, as_of: date) -> ReceivablesMetrics:
        unpaid = 0
        partial = 0
        overpaid = 0
        due_today = 0
        overdue = 0
        seriously_overdue = 0
        settled = 0
        collection_days: list[Decimal] = []
        open_invoice_ids: list[str] = []
        balances: defaultdict[str, Decimal] = defaultdict(lambda: Decimal("0"))
        aging: dict[str, dict[str, object]] = {
            key: {"invoices": 0, "balances": defaultdict(lambda: Decimal("0"))}
            for key in _AGING_KEYS
        }

        for row in rows:
            total_amount = Decimal(row.total)
            paid_amount = Decimal(row.paid_amount)
            outstanding = total_amount - paid_amount
            if total_amount > 0 and paid_amount == 0:
                unpaid += 1
            elif paid_amount > 0 and outstanding > 0:
                partial += 1
            elif paid_amount > total_amount:
                overpaid += 1

            if total_amount > 0 and paid_amount >= total_amount and row.latest_payment_date:
                days_to_collect = (row.latest_payment_date - row.issue_date).days
                if days_to_collect >= 0:
                    settled += 1
                    collection_days.append(Decimal(days_to_collect))

            if outstanding <= 0:
                continue
            open_invoice_ids.append(row.id)
            balances[row.currency_code] += outstanding
            bucket, days_overdue = self._aging_bucket(row.due_date, as_of)
            aging[bucket]["invoices"] = int(aging[bucket]["invoices"]) + 1
            bucket_balances = aging[bucket]["balances"]
            assert isinstance(bucket_balances, defaultdict)
            bucket_balances[row.currency_code] += outstanding
            if bucket == "due_today":
                due_today += 1
            elif days_overdue and days_overdue > 0:
                overdue += 1
                if days_overdue > 90:
                    seriously_overdue += 1

        currency_mismatches = int(
            self._db.scalar(
                select(func.count(PaymentRecord.id))
                .join(InvoiceRecord, InvoiceRecord.id == PaymentRecord.invoice_id)
                .where(
                    InvoiceRecord.company_id == company_id,
                    InvoiceRecord.invoice_type == "sale",
                    PaymentRecord.company_id == company_id,
                    PaymentRecord.currency_code != InvoiceRecord.currency_code,
                )
            )
            or 0
        )
        missing_due_date = int(
            self._db.scalar(
                select(func.count(InvoiceRecord.id)).where(
                    InvoiceRecord.company_id == company_id,
                    InvoiceRecord.invoice_type == "sale",
                    InvoiceRecord.due_date.is_(None),
                )
            )
            or 0
        )
        followup_metrics = self._followup_metrics(company_id, open_invoice_ids, as_of)

        average_days = (
            (sum(collection_days) / len(collection_days)).quantize(_CENT, rounding=ROUND_HALF_UP)
            if collection_days
            else None
        )
        return ReceivablesMetrics(
            as_of_date=as_of,
            sales_invoices=len(rows),
            open_sales_invoices=unpaid + partial,
            unpaid_sales_invoices=unpaid,
            partially_paid_sales_invoices=partial,
            overpaid_sales_invoices=overpaid,
            payments_with_currency_mismatch=currency_mismatches,
            sales_invoices_missing_due_date=missing_due_date,
            due_today_sales_invoices=due_today,
            overdue_sales_invoices=overdue,
            seriously_overdue_sales_invoices=seriously_overdue,
            pending_collection_followups=followup_metrics["pending"],
            open_payment_promises=followup_metrics["open_promises"],
            broken_payment_promises=followup_metrics["broken_promises"],
            settled_sales_invoices=settled,
            average_days_to_collect=average_days,
            outstanding_balances=self._balances(balances),
            aging_buckets=tuple(
                ReceivablesAgingBucket(
                    key=key,
                    invoices=int(aging[key]["invoices"]),
                    outstanding_balances=self._balances(aging[key]["balances"]),
                )
                for key in _AGING_KEYS
                if int(aging[key]["invoices"])
            ),
        )

    def _followup_metrics(
        self,
        company_id: str,
        open_invoice_ids: list[str],
        as_of: date,
    ) -> dict[str, int]:
        if not open_invoice_ids:
            return {"pending": 0, "open_promises": 0, "broken_promises": 0}
        records = self._db.scalars(
            select(CollectionFollowUpRecord)
            .where(
                CollectionFollowUpRecord.company_id == company_id,
                CollectionFollowUpRecord.invoice_id.in_(open_invoice_ids),
            )
            .order_by(
                CollectionFollowUpRecord.invoice_id.asc(),
                CollectionFollowUpRecord.updated_at.desc(),
                CollectionFollowUpRecord.created_at.desc(),
                CollectionFollowUpRecord.id.desc(),
            )
        )
        latest: dict[str, CollectionFollowUpRecord] = {}
        for record in records:
            latest.setdefault(record.invoice_id, record)

        metrics = {"pending": 0, "open_promises": 0, "broken_promises": 0}
        for record in latest.values():
            if record.status == CollectionFollowUpStatus.PENDING.value:
                metrics["pending"] += 1
            if record.status != CollectionFollowUpStatus.PROMISE_TO_PAY.value:
                continue
            if record.promised_date is not None and record.promised_date < as_of:
                metrics["broken_promises"] += 1
            else:
                metrics["open_promises"] += 1
        return metrics

    def _findings(
        self, metrics: ReceivablesMetrics, company_id: str
    ) -> list[ReceivablesFinding]:
        findings: list[ReceivablesFinding] = []
        if metrics.sales_invoices == 0:
            findings.append(
                self._finding(
                    "NO_SALES_INVOICES",
                    ReceivablesSeverity.INFO,
                    "No hay facturas de venta para analizar la cartera.",
                    {"invoices": 0},
                    "Importa o registra facturas de venta para obtener una cartera verificable.",
                )
            )
        if metrics.unpaid_sales_invoices:
            findings.append(
                self._finding(
                    "UNPAID_SALES_INVOICES",
                    ReceivablesSeverity.WARNING,
                    "Hay facturas de venta sin pagos registrados.",
                    {"invoices": metrics.unpaid_sales_invoices},
                    "Confirma su estado de cobro y registra o relaciona los pagos recibidos.",
                )
            )
        if metrics.partially_paid_sales_invoices:
            findings.append(
                self._finding(
                    "PARTIALLY_PAID_SALES_INVOICES",
                    ReceivablesSeverity.WARNING,
                    "Hay facturas de venta con pagos parciales.",
                    {"invoices": metrics.partially_paid_sales_invoices},
                    "Prioriza el seguimiento de los saldos pendientes antes de iniciar un nuevo cobro.",
                )
            )
        if metrics.overpaid_sales_invoices:
            findings.append(
                self._finding(
                    "OVERPAID_SALES_INVOICES",
                    ReceivablesSeverity.WARNING,
                    "Hay facturas de venta con pagos superiores al total en la misma moneda.",
                    {"invoices": metrics.overpaid_sales_invoices},
                    "Revisa pagos duplicados, anticipos o notas de ajuste antes de aplicar nuevos cobros.",
                )
            )
        if metrics.sales_invoices_missing_due_date:
            findings.append(
                self._finding(
                    "SALES_INVOICES_MISSING_DUE_DATE",
                    ReceivablesSeverity.WARNING,
                    "Hay facturas de venta sin fecha de vencimiento verificable.",
                    {"invoices": metrics.sales_invoices_missing_due_date},
                    "Completa el vencimiento o las condiciones de pago para medir correctamente la antigüedad.",
                )
            )
        if metrics.overdue_sales_invoices:
            findings.append(
                self._finding(
                    "OVERDUE_SALES_INVOICES",
                    ReceivablesSeverity.WARNING,
                    "Hay facturas de venta vencidas con saldo pendiente.",
                    {"invoices": metrics.overdue_sales_invoices},
                    "Revisa el seguimiento confirmado y la evidencia de pago antes de escalar la gestión.",
                )
            )
        if metrics.seriously_overdue_sales_invoices:
            findings.append(
                self._finding(
                    "SERIOUSLY_OVERDUE_SALES_INVOICES",
                    ReceivablesSeverity.CRITICAL,
                    "Hay cartera vencida por más de noventa días.",
                    {"invoices": metrics.seriously_overdue_sales_invoices},
                    "Prioriza una revisión humana de soportes, acuerdos y posibles ajustes contables.",
                )
            )
        if metrics.broken_payment_promises:
            findings.append(
                self._finding(
                    "BROKEN_PAYMENT_PROMISES",
                    ReceivablesSeverity.WARNING,
                    "Hay promesas de pago cuya fecha ya pasó y conservan saldo abierto.",
                    {"followups": metrics.broken_payment_promises},
                    "Confirma el recaudo o actualiza el seguimiento antes de tomar una nueva decisión.",
                )
            )
        if metrics.open_payment_promises:
            findings.append(
                self._finding(
                    "OPEN_PAYMENT_PROMISES",
                    ReceivablesSeverity.INFO,
                    "Hay promesas de pago activas con saldo pendiente.",
                    {"followups": metrics.open_payment_promises},
                    "Verifica la evidencia de pago en la fecha prometida antes de cambiar el estado.",
                )
            )
        invoices_without_customer = int(
            self._db.scalar(
                select(func.count(InvoiceRecord.id)).where(
                    InvoiceRecord.company_id == company_id,
                    InvoiceRecord.invoice_type == "sale",
                    InvoiceRecord.recipient_party_id.is_(None),
                )
            )
            or 0
        )
        if invoices_without_customer:
            findings.append(
                self._finding(
                    "SALES_INVOICES_WITHOUT_CUSTOMER",
                    ReceivablesSeverity.WARNING,
                    "Hay facturas de venta sin cliente asociado.",
                    {"invoices": invoices_without_customer},
                    "Relaciona cada factura con su cliente antes de gestionar el cobro.",
                )
            )
        if metrics.payments_with_currency_mismatch:
            findings.append(
                self._finding(
                    "PAYMENTS_WITH_CURRENCY_MISMATCH",
                    ReceivablesSeverity.INFO,
                    "Hay pagos vinculados en una moneda distinta a la factura de venta.",
                    {"payments": metrics.payments_with_currency_mismatch},
                    "Revisa la tasa aplicada antes de interpretar el saldo de esas facturas.",
                )
            )
        return findings

    @staticmethod
    def _aging_bucket(due_date: date | None, as_of: date) -> tuple[str, int | None]:
        if due_date is None:
            return "missing_due_date", None
        days_overdue = (as_of - due_date).days
        if days_overdue < 0:
            return "not_due", 0
        if days_overdue == 0:
            return "due_today", 0
        if days_overdue <= 30:
            return "overdue_1_30", days_overdue
        if days_overdue <= 60:
            return "overdue_31_60", days_overdue
        if days_overdue <= 90:
            return "overdue_61_90", days_overdue
        return "overdue_91_plus", days_overdue

    @staticmethod
    def _balances(values) -> tuple[ReceivablesBalance, ...]:
        return tuple(
            ReceivablesBalance(currency_code=currency, amount=amount.quantize(_CENT))
            for currency, amount in sorted(values.items())
        )

    @staticmethod
    def _finding(
        code: str,
        severity: ReceivablesSeverity,
        message: str,
        evidence: dict[str, int],
        recommendation: str,
    ) -> ReceivablesFinding:
        return ReceivablesFinding(
            code=code,
            severity=severity,
            message=message,
            evidence=evidence,
            recommendation=recommendation,
        )

    @staticmethod
    def _summary(findings: list[ReceivablesFinding]) -> ReceivablesSummary:
        critical_count = sum(finding.severity is ReceivablesSeverity.CRITICAL for finding in findings)
        warning_count = sum(finding.severity is ReceivablesSeverity.WARNING for finding in findings)
        info_count = sum(finding.severity is ReceivablesSeverity.INFO for finding in findings)
        status = (
            ReceivablesStatus.CRITICAL
            if critical_count
            else ReceivablesStatus.NEEDS_ATTENTION
            if warning_count
            else ReceivablesStatus.HEALTHY
        )
        return ReceivablesSummary(
            status=status,
            finding_count=len(findings),
            critical_count=critical_count,
            warning_count=warning_count,
            info_count=info_count,
        )
