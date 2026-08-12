"""Casos de uso para el seguimiento operativo de cartera."""

import re

from datetime import date
from enum import Enum
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.accounting import InvoiceRecord
from app.models.collection_followup import CollectionFollowUpRecord
from app.shared.errors import app_error


class CollectionFollowUpStatus(str, Enum):
    """Estados de un registro de seguimiento; no activan ning\u00fan cobro."""

    PENDING = "pending"
    CONTACTED = "contacted"
    PROMISE_TO_PAY = "promise_to_pay"
    RESOLVED = "resolved"
    CANCELLED = "cancelled"


_EMAIL_PATTERN = re.compile(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b")
_DIRECT_IDENTIFIER_PATTERN = re.compile(r"(?<!\d)(?:\d[ .-]?){7,}\d(?!\d)")
_URL_PATTERN = re.compile(r"\b(?:https?://|www\.)", re.IGNORECASE)
_MAX_NOTE_LENGTH = 280


class CollectionFollowUpService:
    """Persiste trazabilidad de cobro sin enviar comunicaciones ni pagos."""

    def __init__(self, db: Session) -> None:
        self._db = db

    def list_followups(
        self, company_id: UUID, *, invoice_id: UUID | None = None
    ) -> list[CollectionFollowUpRecord]:
        statement = select(CollectionFollowUpRecord).where(
            CollectionFollowUpRecord.company_id == str(company_id)
        )
        if invoice_id is not None:
            statement = statement.where(CollectionFollowUpRecord.invoice_id == str(invoice_id))
        return list(
            self._db.scalars(
                statement.order_by(
                    CollectionFollowUpRecord.updated_at.desc(),
                    CollectionFollowUpRecord.created_at.desc(),
                )
            )
        )

    def create_followup(
        self,
        company_id: UUID,
        *,
        invoice_id: UUID,
        status: CollectionFollowUpStatus,
        promised_date: date | None,
        note: str | None,
        actor_user_id: int,
    ) -> CollectionFollowUpRecord:
        self._require_sales_invoice(company_id, invoice_id)
        self._validate_promise_date(status, promised_date)
        record = CollectionFollowUpRecord(
            id=str(uuid4()),
            company_id=str(company_id),
            invoice_id=str(invoice_id),
            status=status.value,
            promised_date=promised_date,
            note=self._safe_note(note),
            created_by_user_id=actor_user_id,
            updated_by_user_id=actor_user_id,
        )
        self._db.add(record)
        self._db.commit()
        self._db.refresh(record)
        return record

    def update_followup(
        self,
        company_id: UUID,
        followup_id: UUID,
        *,
        status: CollectionFollowUpStatus | None,
        promised_date: date | None,
        note: str | None,
        fields_set: set[str],
        actor_user_id: int,
    ) -> CollectionFollowUpRecord:
        changed_fields = {"status", "promised_date", "note"}.intersection(fields_set)
        if not changed_fields:
            raise app_error(
                "VALIDATION_ERROR",
                message="Indica al menos un dato operativo para actualizar el seguimiento.",
            )
        if "status" in changed_fields and status is None:
            raise app_error(
                "VALIDATION_ERROR",
                message="El estado no puede ser nulo cuando se incluye en la actualizaci\u00f3n.",
            )
        record = self._db.scalar(
            select(CollectionFollowUpRecord).where(
                CollectionFollowUpRecord.id == str(followup_id),
                CollectionFollowUpRecord.company_id == str(company_id),
            )
        )
        if record is None:
            raise app_error("NOT_FOUND", message="Seguimiento de cobro no encontrado.")
        next_status = status if "status" in changed_fields else CollectionFollowUpStatus(record.status)
        next_promised_date = (
            promised_date if "promised_date" in changed_fields else record.promised_date
        )
        self._validate_promise_date(next_status, next_promised_date)
        if "status" in changed_fields and status is not None:
            record.status = status.value
        if "promised_date" in changed_fields:
            record.promised_date = promised_date
        if "note" in changed_fields:
            record.note = self._safe_note(note)
        record.updated_by_user_id = actor_user_id
        self._db.commit()
        self._db.refresh(record)
        return record

    def _require_sales_invoice(self, company_id: UUID, invoice_id: UUID) -> None:
        invoice = self._db.scalar(
            select(InvoiceRecord.id).where(
                InvoiceRecord.id == str(invoice_id),
                InvoiceRecord.company_id == str(company_id),
                InvoiceRecord.invoice_type == "sale",
            )
        )
        if invoice is None:
            raise app_error(
                "NOT_FOUND",
                message="Factura de venta no encontrada para esta empresa.",
            )

    @staticmethod
    def _safe_note(note: str | None) -> str | None:
        if note is None:
            return None
        normalized = " ".join(note.split())
        if not normalized:
            return None
        if len(normalized) > _MAX_NOTE_LENGTH:
            raise app_error(
                "VALIDATION_ERROR",
                message="La nota operativa no puede superar 280 caracteres.",
            )
        if (
            _EMAIL_PATTERN.search(normalized)
            or _DIRECT_IDENTIFIER_PATTERN.search(normalized)
            or _URL_PATTERN.search(normalized)
        ):
            raise app_error(
                "VALIDATION_ERROR",
                message=(
                    "La nota no puede incluir correos, tel\u00e9fonos, documentos, cuentas ni enlaces. "
                    "Usa solo un resumen operativo sin datos personales."
                ),
            )
        return normalized

    @staticmethod
    def _validate_promise_date(
        status: CollectionFollowUpStatus, promised_date: date | None
    ) -> None:
        if status is CollectionFollowUpStatus.PROMISE_TO_PAY and promised_date is None:
            raise app_error(
                "VALIDATION_ERROR",
                message="Una promesa de pago requiere una fecha prometida.",
            )
        if status is not CollectionFollowUpStatus.PROMISE_TO_PAY and promised_date is not None:
            raise app_error(
                "VALIDATION_ERROR",
                message="La fecha prometida solo aplica a una promesa de pago.",
            )
