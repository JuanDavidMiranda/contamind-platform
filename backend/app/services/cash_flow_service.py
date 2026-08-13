"""Proyección determinista de movimientos abiertos por vencimiento."""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import UUID

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from app.ai.agents.cash_flow.schemas import (
    CashFlowAmount,
    CashFlowFinding,
    CashFlowMetrics,
    CashFlowPeriod,
    CashFlowReport,
    CashFlowSeverity,
    CashFlowStatus,
    CashFlowSummary,
)
from app.models.accounting import InvoiceRecord, PaymentRecord


_CENT = Decimal("0.01")
_HORIZON_DAYS = 90
_PERIOD_KEYS = (
    "overdue",
    "due_today",
    "next_7_days",
    "days_8_30",
    "days_31_60",
    "days_61_90",
    "beyond_90",
)


class CashFlowService:
    """Agrupa cobros y pagos abiertos sin afirmar disponibilidad de caja."""

    def __init__(self, db: Session) -> None:
        self._db = db

    def analyze(
        self,
        company_id: UUID,
        *,
        as_of: date | None = None,
    ) -> CashFlowReport:
        analysis_date = as_of or datetime.now(UTC).date()
        rows = self._open_invoice_rows(str(company_id))
        metrics = self._metrics(rows, analysis_date)
        findings = self._findings(metrics)
        summary = self._summary(findings)
        return CashFlowReport(
            company_id=company_id,
            generated_at=datetime.now(UTC),
            overall_status=summary.status,
            summary=summary,
            metrics=metrics,
            findings=tuple(findings),
        )

    def _open_invoice_rows(self, company_id: str):
        paid_amount = func.coalesce(func.sum(PaymentRecord.amount), Decimal("0"))
        return self._db.execute(
            select(
                InvoiceRecord.id,
                InvoiceRecord.invoice_type,
                InvoiceRecord.due_date,
                InvoiceRecord.currency_code,
                InvoiceRecord.total,
                paid_amount.label("paid_amount"),
            )
            .outerjoin(PaymentRecord, self._matching_payment_join())
            .where(
                InvoiceRecord.company_id == company_id,
                InvoiceRecord.invoice_type.in_(("sale", "purchase")),
            )
            .group_by(
                InvoiceRecord.id,
                InvoiceRecord.invoice_type,
                InvoiceRecord.due_date,
                InvoiceRecord.currency_code,
                InvoiceRecord.total,
            )
            .having(paid_amount < InvoiceRecord.total)
        ).all()

    def _metrics(self, rows, as_of: date) -> CashFlowMetrics:
        periods = {
            key: {
                "receivables": 0,
                "payables": 0,
                "inflows": defaultdict(lambda: Decimal("0")),
                "outflows": defaultdict(lambda: Decimal("0")),
            }
            for key in _PERIOD_KEYS
        }
        open_receivables = 0
        open_payables = 0
        scheduled_receivables = 0
        scheduled_payables = 0
        receivables_missing_due_date = 0
        payables_missing_due_date = 0
        currencies: set[str] = set()

        for row in rows:
            outstanding = (Decimal(row.total) - Decimal(row.paid_amount)).quantize(_CENT)
            if outstanding <= 0:
                continue
            is_receivable = row.invoice_type == "sale"
            if is_receivable:
                open_receivables += 1
            else:
                open_payables += 1
            currencies.add(row.currency_code)
            if row.due_date is None:
                if is_receivable:
                    receivables_missing_due_date += 1
                else:
                    payables_missing_due_date += 1
                continue

            period_key = self._period_key(row.due_date, as_of)
            if is_receivable:
                scheduled_receivables += 1
                periods[period_key]["receivables"] += 1
                periods[period_key]["inflows"][row.currency_code] += outstanding
            else:
                scheduled_payables += 1
                periods[period_key]["payables"] += 1
                periods[period_key]["outflows"][row.currency_code] += outstanding

        period_models = tuple(
            self._period_model(key, periods[key], as_of)
            for key in _PERIOD_KEYS
            if periods[key]["receivables"] or periods[key]["payables"]
        )
        horizon_periods = {
            "overdue",
            "due_today",
            "next_7_days",
            "days_8_30",
            "days_31_60",
            "days_61_90",
        }
        horizon_inflows: defaultdict[str, Decimal] = defaultdict(lambda: Decimal("0"))
        horizon_outflows: defaultdict[str, Decimal] = defaultdict(lambda: Decimal("0"))
        for period in period_models:
            if period.key not in horizon_periods:
                continue
            for amount in period.projected_inflows:
                horizon_inflows[amount.currency_code] += amount.amount
            for amount in period.projected_outflows:
                horizon_outflows[amount.currency_code] += amount.amount

        return CashFlowMetrics(
            as_of_date=as_of,
            horizon_days=_HORIZON_DAYS,
            open_receivables=open_receivables,
            open_payables=open_payables,
            scheduled_receivables=scheduled_receivables,
            scheduled_payables=scheduled_payables,
            receivables_missing_due_date=receivables_missing_due_date,
            payables_missing_due_date=payables_missing_due_date,
            currencies=len(currencies),
            projected_inflows_90d=self._amounts(horizon_inflows),
            projected_outflows_90d=self._amounts(horizon_outflows),
            net_movements_90d=self._net_amounts(horizon_inflows, horizon_outflows),
            cash_flow_periods=period_models,
        )

    def _period_model(self, key: str, values: dict[str, object], as_of: date) -> CashFlowPeriod:
        inflows = values["inflows"]
        outflows = values["outflows"]
        assert isinstance(inflows, defaultdict)
        assert isinstance(outflows, defaultdict)
        start_date, end_date = self._period_dates(key, as_of)
        return CashFlowPeriod(
            key=key,
            start_date=start_date,
            end_date=end_date,
            receivable_invoices=int(values["receivables"]),
            payable_invoices=int(values["payables"]),
            projected_inflows=self._amounts(inflows),
            projected_outflows=self._amounts(outflows),
            net_movements=self._net_amounts(inflows, outflows),
        )

    @staticmethod
    def _period_key(due_date: date, as_of: date) -> str:
        days = (due_date - as_of).days
        if days < 0:
            return "overdue"
        if days == 0:
            return "due_today"
        if days <= 7:
            return "next_7_days"
        if days <= 30:
            return "days_8_30"
        if days <= 60:
            return "days_31_60"
        if days <= 90:
            return "days_61_90"
        return "beyond_90"

    @staticmethod
    def _period_dates(key: str, as_of: date) -> tuple[date | None, date | None]:
        offsets = {
            "overdue": (None, -1),
            "due_today": (0, 0),
            "next_7_days": (1, 7),
            "days_8_30": (8, 30),
            "days_31_60": (31, 60),
            "days_61_90": (61, 90),
            "beyond_90": (91, None),
        }
        start, end = offsets[key]
        return (
            as_of + timedelta(days=start) if start is not None else None,
            as_of + timedelta(days=end) if end is not None else None,
        )

    @staticmethod
    def _amounts(values: dict[str, Decimal]) -> tuple[CashFlowAmount, ...]:
        return tuple(
            CashFlowAmount(currency_code=currency, amount=amount.quantize(_CENT))
            for currency, amount in sorted(values.items())
            if amount
        )

    @classmethod
    def _net_amounts(
        cls,
        inflows: dict[str, Decimal],
        outflows: dict[str, Decimal],
    ) -> tuple[CashFlowAmount, ...]:
        currencies = sorted(set(inflows) | set(outflows))
        return tuple(
            CashFlowAmount(
                currency_code=currency,
                amount=(inflows.get(currency, Decimal("0")) - outflows.get(currency, Decimal("0"))).quantize(_CENT),
            )
            for currency in currencies
        )

    @staticmethod
    def _findings(metrics: CashFlowMetrics) -> list[CashFlowFinding]:
        findings: list[CashFlowFinding] = []
        missing_dates = (
            metrics.receivables_missing_due_date + metrics.payables_missing_due_date
        )
        if not metrics.open_receivables and not metrics.open_payables:
            findings.append(
                CashFlowFinding(
                    code="NO_OPEN_CASH_FLOW_ITEMS",
                    severity=CashFlowSeverity.INFO,
                    message="No hay facturas abiertas para proyectar movimientos de caja.",
                    evidence={"invoices": 0},
                    recommendation="Registra o importa facturas abiertas para construir la proyección.",
                )
            )
        if missing_dates:
            findings.append(
                CashFlowFinding(
                    code="CASH_FLOW_ITEMS_MISSING_DUE_DATE",
                    severity=CashFlowSeverity.WARNING,
                    message="Hay movimientos abiertos sin fecha de vencimiento y no entran en la proyección temporal.",
                    evidence={
                        "receivables": metrics.receivables_missing_due_date,
                        "payables": metrics.payables_missing_due_date,
                    },
                    recommendation="Completa los vencimientos en cartera y cuentas por pagar antes de usar la proyección para priorizar.",
                )
            )
        negative_currencies = sum(
            amount.amount < 0 for amount in metrics.net_movements_90d
        )
        if negative_currencies:
            findings.append(
                CashFlowFinding(
                    code="NEGATIVE_NET_MOVEMENT_WITHIN_90_DAYS",
                    severity=CashFlowSeverity.WARNING,
                    message="En una o más monedas, las salidas programadas superan las entradas abiertas dentro de noventa días.",
                    evidence={"currencies": negative_currencies},
                    recommendation="Revisa por moneda los vencimientos, la certeza de recaudo y la disponibilidad bancaria fuera de este reporte.",
                )
            )
        overdue_period = next(
            (period for period in metrics.cash_flow_periods if period.key == "overdue"),
            None,
        )
        if overdue_period and overdue_period.receivable_invoices:
            findings.append(
                CashFlowFinding(
                    code="OVERDUE_RECEIVABLES_ARE_NOT_CONFIRMED_CASH",
                    severity=CashFlowSeverity.INFO,
                    message="La proyección incluye cartera vencida como entrada pendiente, no como efectivo confirmado.",
                    evidence={"invoices": overdue_period.receivable_invoices},
                    recommendation="Confirma el recaudo y actualiza los pagos antes de interpretar esas entradas.",
                )
            )
        return findings

    @staticmethod
    def _summary(findings: list[CashFlowFinding]) -> CashFlowSummary:
        warning_count = sum(
            finding.severity is CashFlowSeverity.WARNING for finding in findings
        )
        info_count = sum(
            finding.severity is CashFlowSeverity.INFO for finding in findings
        )
        status = (
            CashFlowStatus.NEEDS_ATTENTION
            if warning_count
            else CashFlowStatus.HEALTHY
        )
        return CashFlowSummary(
            status=status,
            finding_count=len(findings),
            warning_count=warning_count,
            info_count=info_count,
        )

    @staticmethod
    def _matching_payment_join():
        return and_(
            PaymentRecord.invoice_id == InvoiceRecord.id,
            PaymentRecord.company_id == InvoiceRecord.company_id,
            PaymentRecord.currency_code == InvoiceRecord.currency_code,
        )
