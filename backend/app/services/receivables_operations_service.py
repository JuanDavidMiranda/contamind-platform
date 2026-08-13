"""Consultas y correcciones operativas de cartera con alcance por empresa."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import and_, case, func, select
from sqlalchemy.orm import Session

from app.models.accounting import InvoiceRecord, PaymentRecord
from app.models.collection_followup import CollectionFollowUpRecord
from app.services.manual_accounting_service import ManualAccountingService
from app.shared.errors import app_error


@dataclass(frozen=True)
class OpenReceivableItem:
    """Factura de venta abierta, sin datos de terceros ni contenido de notas."""

    invoice_id: UUID
    invoice_number: str | None
    issue_date: date
    due_date: date | None
    payment_terms_days: int | None
    currency_code: str
    total_amount: Decimal
    paid_amount: Decimal
    outstanding_amount: Decimal
    days_overdue: int | None
    aging_bucket: str
    latest_followup_status: str | None
    promised_date: date | None
    mismatched_payment_count: int


@dataclass(frozen=True)
class OpenReceivablesPage:
    as_of: date
    total: int
    items: tuple[OpenReceivableItem, ...]


class ReceivablesOperationsService:
    """Expone cartera abierta y permite corregir sus condiciones con confirmación externa.

    Los pagos sólo disminuyen una factura cuando comparten moneda. Esto conserva la
    misma regla del diagnóstico del agente y evita ocultar diferencias cambiarias.
    """

    def __init__(self, db: Session) -> None:
        self._db = db

    def open_items(
        self,
        company_id: UUID,
        *,
        as_of: date,
        limit: int,
        offset: int,
        invoice_type: str = "sale",
        include_collection_followups: bool = True,
    ) -> OpenReceivablesPage:
        company_key = str(company_id)
        total = self._open_item_count(company_key, invoice_type=invoice_type)
        rows = self._open_item_rows(
            company_key,
            invoice_type=invoice_type,
            limit=limit,
            offset=offset,
        )
        invoice_ids = [row.id for row in rows]
        latest_followups = (
            self._latest_followups(company_key, invoice_ids)
            if include_collection_followups
            else {}
        )
        mismatches = self._mismatched_payment_counts(company_key, invoice_ids)

        items = tuple(
            self._to_open_item(
                row,
                as_of=as_of,
                latest_followup=latest_followups.get(row.id),
                mismatched_payment_count=mismatches.get(row.id, 0),
            )
            for row in rows
        )
        return OpenReceivablesPage(as_of=as_of, total=total, items=items)

    def update_terms(
        self,
        company_id: UUID,
        invoice_id: UUID,
        *,
        due_date: date | None,
        payment_terms_days: int | None,
        fields_set: set[str],
        actor_user_id: int,
        invoice_type: str = "sale",
        invoice_label: str = "Factura de venta",
    ) -> InvoiceRecord:
        """Actualiza el vencimiento como enriquecimiento operativo trazable.

        Un plazo sin fecha deriva el vencimiento. Una fecha explícita sin plazo se
        conserva como fecha pactada y limpia el plazo calculado; ambos valores se
        validan cuando llegan juntos. Un ``due_date: null`` limpia ambas referencias.
        """

        provided = {"due_date", "payment_terms_days"}.intersection(fields_set)
        if not provided:
            raise app_error(
                "VALIDATION_ERROR",
                message="Indica una fecha de vencimiento, un plazo de pago o una limpieza explícita.",
            )

        record = self._db.scalar(
            select(InvoiceRecord).where(
                InvoiceRecord.id == str(invoice_id),
                InvoiceRecord.company_id == str(company_id),
                InvoiceRecord.invoice_type == invoice_type,
            )
        )
        if record is None:
            raise app_error("NOT_FOUND", message=f"{invoice_label} no encontrada para esta empresa.")

        if provided == {"due_date"}:
            if due_date is None:
                record.due_date = None
                record.payment_terms_days = None
            else:
                record.due_date = ManualAccountingService._resolve_due_date(
                    record.issue_date,
                    due_date,
                    None,
                )
                record.payment_terms_days = None
        elif provided == {"payment_terms_days"}:
            if payment_terms_days is None:
                record.payment_terms_days = None
            else:
                record.due_date = ManualAccountingService._resolve_due_date(
                    record.issue_date,
                    None,
                    payment_terms_days,
                )
                record.payment_terms_days = payment_terms_days
        elif due_date is None and payment_terms_days is None:
            record.due_date = None
            record.payment_terms_days = None
        else:
            resolved_due_date = ManualAccountingService._resolve_due_date(
                record.issue_date,
                due_date,
                payment_terms_days,
            )
            if resolved_due_date is None:
                raise app_error(
                    "VALIDATION_ERROR",
                    message="La fecha de vencimiento o el plazo de pago son obligatorios para esta actualización.",
                )
            record.due_date = resolved_due_date
            record.payment_terms_days = payment_terms_days

        record.updated_by_user_id = actor_user_id
        self._db.commit()
        self._db.refresh(record)
        return record

    def _open_item_count(self, company_id: str, *, invoice_type: str) -> int:
        paid_amount = self._paid_amount()
        statement = (
            select(InvoiceRecord.id)
            .outerjoin(PaymentRecord, self._matching_payment_join())
            .where(
                InvoiceRecord.company_id == company_id,
                InvoiceRecord.invoice_type == invoice_type,
            )
            .group_by(InvoiceRecord.id, InvoiceRecord.total)
            .having(paid_amount < InvoiceRecord.total)
            .subquery()
        )
        return int(self._db.scalar(select(func.count()).select_from(statement)) or 0)

    def _open_item_rows(
        self,
        company_id: str,
        *,
        invoice_type: str,
        limit: int,
        offset: int,
    ):
        paid_amount = self._paid_amount()
        overdue_order = case((InvoiceRecord.due_date.is_(None), 1), else_=0)
        return self._db.execute(
            select(
                InvoiceRecord.id,
                InvoiceRecord.number,
                InvoiceRecord.issue_date,
                InvoiceRecord.due_date,
                InvoiceRecord.payment_terms_days,
                InvoiceRecord.currency_code,
                InvoiceRecord.total,
                paid_amount.label("paid_amount"),
            )
            .outerjoin(PaymentRecord, self._matching_payment_join())
            .where(
                InvoiceRecord.company_id == company_id,
                InvoiceRecord.invoice_type == invoice_type,
            )
            .group_by(
                InvoiceRecord.id,
                InvoiceRecord.number,
                InvoiceRecord.issue_date,
                InvoiceRecord.due_date,
                InvoiceRecord.payment_terms_days,
                InvoiceRecord.currency_code,
                InvoiceRecord.total,
            )
            .having(paid_amount < InvoiceRecord.total)
            .order_by(
                overdue_order,
                InvoiceRecord.due_date.asc(),
                InvoiceRecord.issue_date.asc(),
                InvoiceRecord.id.asc(),
            )
            .offset(offset)
            .limit(limit)
        ).all()

    @staticmethod
    def _paid_amount():
        return func.coalesce(func.sum(PaymentRecord.amount), Decimal("0"))

    @staticmethod
    def _matching_payment_join():
        return and_(
            PaymentRecord.invoice_id == InvoiceRecord.id,
            PaymentRecord.company_id == InvoiceRecord.company_id,
            PaymentRecord.currency_code == InvoiceRecord.currency_code,
        )

    def _latest_followups(
        self,
        company_id: str,
        invoice_ids: Sequence[str],
    ) -> dict[str, CollectionFollowUpRecord]:
        if not invoice_ids:
            return {}
        records = self._db.scalars(
            select(CollectionFollowUpRecord)
            .where(
                CollectionFollowUpRecord.company_id == company_id,
                CollectionFollowUpRecord.invoice_id.in_(invoice_ids),
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
        return latest

    def _mismatched_payment_counts(
        self,
        company_id: str,
        invoice_ids: Sequence[str],
    ) -> dict[str, int]:
        if not invoice_ids:
            return {}
        rows = self._db.execute(
            select(PaymentRecord.invoice_id, func.count(PaymentRecord.id))
            .join(InvoiceRecord, InvoiceRecord.id == PaymentRecord.invoice_id)
            .where(
                PaymentRecord.company_id == company_id,
                PaymentRecord.invoice_id.in_(invoice_ids),
                PaymentRecord.currency_code != InvoiceRecord.currency_code,
            )
            .group_by(PaymentRecord.invoice_id)
        ).all()
        return {invoice_id: int(count) for invoice_id, count in rows if invoice_id is not None}

    @staticmethod
    def _to_open_item(
        row,
        *,
        as_of: date,
        latest_followup: CollectionFollowUpRecord | None,
        mismatched_payment_count: int,
    ) -> OpenReceivableItem:
        total_amount = Decimal(row.total)
        paid_amount = Decimal(row.paid_amount)
        outstanding_amount = (total_amount - paid_amount).quantize(Decimal("0.01"))
        days_overdue, aging_bucket = ReceivablesOperationsService._aging(
            row.due_date,
            as_of,
        )
        return OpenReceivableItem(
            invoice_id=UUID(row.id),
            invoice_number=row.number,
            issue_date=row.issue_date,
            due_date=row.due_date,
            payment_terms_days=row.payment_terms_days,
            currency_code=row.currency_code,
            total_amount=total_amount.quantize(Decimal("0.01")),
            paid_amount=paid_amount.quantize(Decimal("0.01")),
            outstanding_amount=outstanding_amount,
            days_overdue=days_overdue,
            aging_bucket=aging_bucket,
            latest_followup_status=latest_followup.status if latest_followup else None,
            promised_date=latest_followup.promised_date if latest_followup else None,
            mismatched_payment_count=mismatched_payment_count,
        )

    @staticmethod
    def _aging(due_date: date | None, as_of: date) -> tuple[int | None, str]:
        if due_date is None:
            return None, "missing_due_date"
        days_overdue = (as_of - due_date).days
        if days_overdue < 0:
            return 0, "not_due"
        if days_overdue == 0:
            return 0, "due_today"
        if days_overdue <= 30:
            return days_overdue, "overdue_1_30"
        if days_overdue <= 60:
            return days_overdue, "overdue_31_60"
        if days_overdue <= 90:
            return days_overdue, "overdue_61_90"
        return days_overdue, "overdue_91_plus"
