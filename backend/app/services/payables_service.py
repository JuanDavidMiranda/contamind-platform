"""Diagnóstico determinista de obligaciones de compra por empresa."""

from collections import defaultdict
from datetime import UTC, date, datetime
from decimal import Decimal, ROUND_HALF_UP
from uuid import UUID

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from app.ai.agents.payables.schemas import (
    PayablesAgingBucket, PayablesBalance, PayablesFinding, PayablesMetrics,
    PayablesReport, PayablesSeverity, PayablesStatus, PayablesSummary,
)
from app.models.accounting import InvoiceRecord, PaymentRecord


_CENT = Decimal("0.01")
_AGING_KEYS = ("not_due", "due_today", "overdue_1_30", "overdue_31_60", "overdue_61_90", "overdue_91_plus", "missing_due_date")


class PayablesService:
    """Calcula obligaciones de compra, sin terceros ni facturas individuales."""

    def __init__(self, db: Session) -> None:
        self._db = db

    def analyze(self, company_id: UUID, *, as_of: date | None = None) -> PayablesReport:
        analysis_date = as_of or datetime.now(UTC).date()
        key = str(company_id)
        rows = self._rows(key)
        metrics = self._metrics(rows, key, analysis_date)
        findings = self._findings(metrics, key)
        summary = self._summary(findings)
        return PayablesReport(
            company_id=company_id, generated_at=datetime.now(UTC), overall_status=summary.status,
            summary=summary, metrics=metrics, findings=tuple(findings),
        )

    def _rows(self, company_id: str):
        paid = func.coalesce(func.sum(PaymentRecord.amount), Decimal("0"))
        latest = func.max(PaymentRecord.payment_date)
        return self._db.execute(
            select(InvoiceRecord.id, InvoiceRecord.issue_date, InvoiceRecord.due_date,
                   InvoiceRecord.currency_code, InvoiceRecord.total, InvoiceRecord.issuer_party_id,
                   paid.label("paid_amount"), latest.label("latest_payment_date"))
            .outerjoin(PaymentRecord, self._matching_payment_join())
            .where(InvoiceRecord.company_id == company_id, InvoiceRecord.invoice_type == "purchase")
            .group_by(InvoiceRecord.id, InvoiceRecord.issue_date, InvoiceRecord.due_date,
                      InvoiceRecord.currency_code, InvoiceRecord.total, InvoiceRecord.issuer_party_id)
        ).all()

    def _metrics(self, rows, company_id: str, as_of: date) -> PayablesMetrics:
        unpaid = partial = overpaid = due_today = overdue = serious = settled = 0
        payment_days: list[Decimal] = []
        balances: defaultdict[str, Decimal] = defaultdict(lambda: Decimal("0"))
        aging: dict[str, dict[str, object]] = {key: {"invoices": 0, "balances": defaultdict(lambda: Decimal("0"))} for key in _AGING_KEYS}
        for row in rows:
            total, paid = Decimal(row.total), Decimal(row.paid_amount)
            outstanding = total - paid
            if total > 0 and paid == 0: unpaid += 1
            elif paid > 0 and outstanding > 0: partial += 1
            elif paid > total: overpaid += 1
            if total > 0 and paid >= total and row.latest_payment_date:
                days = (row.latest_payment_date - row.issue_date).days
                if days >= 0:
                    settled += 1
                    payment_days.append(Decimal(days))
            if outstanding <= 0: continue
            bucket, days_overdue = self._aging_bucket(row.due_date, as_of)
            balances[row.currency_code] += outstanding
            aging[bucket]["invoices"] = int(aging[bucket]["invoices"]) + 1
            bucket_balances = aging[bucket]["balances"]
            assert isinstance(bucket_balances, defaultdict)
            bucket_balances[row.currency_code] += outstanding
            if bucket == "due_today": due_today += 1
            elif days_overdue and days_overdue > 0:
                overdue += 1
                if days_overdue > 90: serious += 1
        mismatch = int(self._db.scalar(
            select(func.count(PaymentRecord.id)).join(InvoiceRecord, InvoiceRecord.id == PaymentRecord.invoice_id)
            .where(InvoiceRecord.company_id == company_id, InvoiceRecord.invoice_type == "purchase",
                   PaymentRecord.company_id == company_id, PaymentRecord.currency_code != InvoiceRecord.currency_code)
        ) or 0)
        missing = int(self._db.scalar(select(func.count(InvoiceRecord.id)).where(
            InvoiceRecord.company_id == company_id, InvoiceRecord.invoice_type == "purchase", InvoiceRecord.due_date.is_(None)
        )) or 0)
        average = (sum(payment_days) / len(payment_days)).quantize(_CENT, rounding=ROUND_HALF_UP) if payment_days else None
        return PayablesMetrics(
            as_of_date=as_of, purchase_invoices=len(rows), open_purchase_invoices=unpaid + partial,
            unpaid_purchase_invoices=unpaid, partially_paid_purchase_invoices=partial,
            overpaid_purchase_invoices=overpaid, payments_with_currency_mismatch=mismatch,
            purchase_invoices_missing_due_date=missing, due_today_purchase_invoices=due_today,
            overdue_purchase_invoices=overdue, seriously_overdue_purchase_invoices=serious,
            settled_purchase_invoices=settled, average_days_to_pay=average,
            outstanding_balances=self._balances(balances),
            aging_buckets=tuple(PayablesAgingBucket(key=key, invoices=int(aging[key]["invoices"]), outstanding_balances=self._balances(aging[key]["balances"])) for key in _AGING_KEYS if int(aging[key]["invoices"])),
        )

    def _findings(self, metrics: PayablesMetrics, company_id: str) -> list[PayablesFinding]:
        findings: list[PayablesFinding] = []
        def add(code: str, severity: PayablesSeverity, message: str, invoices: int, recommendation: str):
            if invoices: findings.append(PayablesFinding(code=code, severity=severity, message=message, evidence={"invoices": invoices}, recommendation=recommendation))
        if not metrics.purchase_invoices:
            findings.append(PayablesFinding(code="NO_PURCHASE_INVOICES", severity=PayablesSeverity.INFO, message="No hay facturas de compra para analizar obligaciones.", evidence={"invoices": 0}, recommendation="Importa o registra facturas de compra para obtener un análisis verificable."))
        add("UNPAID_PURCHASE_INVOICES", PayablesSeverity.WARNING, "Hay facturas de compra sin pagos registrados.", metrics.unpaid_purchase_invoices, "Confirma el estado de pago y registra o relaciona el pago contabilizado.")
        add("PARTIALLY_PAID_PURCHASE_INVOICES", PayablesSeverity.WARNING, "Hay facturas de compra con pagos parciales.", metrics.partially_paid_purchase_invoices, "Revisa el saldo antes de aprobar o registrar un pago adicional.")
        add("OVERPAID_PURCHASE_INVOICES", PayablesSeverity.WARNING, "Hay facturas de compra con pagos superiores al total en la misma moneda.", metrics.overpaid_purchase_invoices, "Revisa pagos duplicados, anticipos o notas de ajuste antes de pagar nuevamente.")
        add("PURCHASE_INVOICES_MISSING_DUE_DATE", PayablesSeverity.WARNING, "Hay facturas de compra sin fecha de vencimiento verificable.", metrics.purchase_invoices_missing_due_date, "Completa el vencimiento o las condiciones de pago para priorizar obligaciones.")
        add("OVERDUE_PURCHASE_INVOICES", PayablesSeverity.WARNING, "Hay facturas de compra vencidas con saldo pendiente.", metrics.overdue_purchase_invoices, "Revisa soportes, aprobación interna y condiciones acordadas antes de programar el pago.")
        add("SERIOUSLY_OVERDUE_PURCHASE_INVOICES", PayablesSeverity.CRITICAL, "Hay obligaciones vencidas por más de noventa días.", metrics.seriously_overdue_purchase_invoices, "Prioriza una revisión humana de soportes, acuerdos y posibles ajustes contables.")
        suppliers_missing = int(self._db.scalar(select(func.count(InvoiceRecord.id)).where(InvoiceRecord.company_id == company_id, InvoiceRecord.invoice_type == "purchase", InvoiceRecord.issuer_party_id.is_(None))) or 0)
        add("PURCHASE_INVOICES_WITHOUT_SUPPLIER", PayablesSeverity.WARNING, "Hay facturas de compra sin proveedor asociado.", suppliers_missing, "Relaciona cada factura con su proveedor antes de gestionar el pago.")
        if metrics.payments_with_currency_mismatch:
            findings.append(PayablesFinding(code="PAYMENTS_WITH_CURRENCY_MISMATCH", severity=PayablesSeverity.INFO, message="Hay pagos vinculados en una moneda distinta a la factura de compra.", evidence={"payments": metrics.payments_with_currency_mismatch}, recommendation="Revisa la tasa aplicada antes de interpretar el saldo de esas facturas."))
        return findings

    @staticmethod
    def _matching_payment_join(): return and_(PaymentRecord.invoice_id == InvoiceRecord.id, PaymentRecord.company_id == InvoiceRecord.company_id, PaymentRecord.currency_code == InvoiceRecord.currency_code)
    @staticmethod
    def _aging_bucket(due_date: date | None, as_of: date) -> tuple[str, int | None]:
        if due_date is None: return "missing_due_date", None
        days = (as_of - due_date).days
        if days < 0: return "not_due", 0
        if days == 0: return "due_today", 0
        if days <= 30: return "overdue_1_30", days
        if days <= 60: return "overdue_31_60", days
        if days <= 90: return "overdue_61_90", days
        return "overdue_91_plus", days
    @staticmethod
    def _balances(values) -> tuple[PayablesBalance, ...]: return tuple(PayablesBalance(currency_code=code, amount=amount.quantize(_CENT)) for code, amount in sorted(values.items()))
    @staticmethod
    def _summary(findings: list[PayablesFinding]) -> PayablesSummary:
        critical = sum(item.severity is PayablesSeverity.CRITICAL for item in findings)
        warning = sum(item.severity is PayablesSeverity.WARNING for item in findings)
        info = sum(item.severity is PayablesSeverity.INFO for item in findings)
        status = PayablesStatus.CRITICAL if critical else PayablesStatus.NEEDS_ATTENTION if warning else PayablesStatus.HEALTHY
        return PayablesSummary(status=status, finding_count=len(findings), critical_count=critical, warning_count=warning, info_count=info)
