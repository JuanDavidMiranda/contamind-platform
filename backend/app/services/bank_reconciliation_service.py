"""Operación determinista de extractos y conciliaciones bancarias."""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from io import StringIO
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.accounting import InvoiceRecord, PaymentRecord
from app.models.bank_reconciliation import (
    BankAccountRecord,
    BankStatementImportRecord,
    BankTransactionRecord,
)
from app.shared.errors import app_error


_CENT = Decimal("0.01")
_DATE_FORMATS = ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y")
_FIELD_ALIASES = {
    "date": ("date", "fecha", "transaction_date"),
    "amount": ("amount", "valor", "monto", "importe"),
    "description": ("description", "descripcion", "concepto", "detalle"),
    "reference": ("reference", "referencia", "id", "numero"),
    "currency": ("currency", "moneda", "currency_code"),
}
_ALIAS_SENSITIVE_PATTERN = re.compile(
    r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b|"
    r"(?<!\d)(?:\d[\s.-]?){7,}\d(?!\d)"
)


@dataclass(frozen=True)
class BankImportRejection:
    row_number: int
    message: str


@dataclass(frozen=True)
class BankImportResult:
    import_id: UUID
    accepted_rows: int
    duplicate_rows: int
    rejections: tuple[BankImportRejection, ...]


@dataclass(frozen=True)
class BankTransactionItem:
    id: UUID
    bank_account_id: UUID
    transaction_date: date
    amount: Decimal
    currency_code: str
    description: str | None
    reference: str | None
    status: str
    match_candidate_count: int
    suggested_payment_id: UUID | None
    suggested_payment_date: date | None
    matched_payment_id: UUID | None
    reviewed_by_user_id: int | None
    reviewed_at: datetime | None


@dataclass(frozen=True)
class BankTransactionPage:
    total: int
    items: tuple[BankTransactionItem, ...]


class BankReconciliationService:
    """Importa extractos y propone coincidencias sin confirmar decisiones humanas."""

    def __init__(self, db: Session) -> None:
        self._db = db

    def create_account(
        self,
        company_id: UUID,
        *,
        name: str,
        bank_name: str | None,
        currency_code: str,
        actor_user_id: int,
    ) -> BankAccountRecord:
        normalized_name = name.strip()
        normalized_bank_name = (bank_name or "").strip() or None
        if _ALIAS_SENSITIVE_PATTERN.search(normalized_name) or (
            normalized_bank_name
            and _ALIAS_SENSITIVE_PATTERN.search(normalized_bank_name)
        ):
            raise app_error(
                "VALIDATION_ERROR",
                message="Usa un alias sin números completos de cuenta, correos ni identificadores personales.",
            )
        existing = self._db.scalar(
            select(BankAccountRecord.id).where(
                BankAccountRecord.company_id == str(company_id),
                func.lower(BankAccountRecord.name) == normalized_name.casefold(),
            )
        )
        if existing is not None:
            raise app_error(
                "CONFLICT",
                message="Ya existe una cuenta bancaria con ese nombre en la empresa.",
            )
        record = BankAccountRecord(
            id=str(uuid4()),
            company_id=str(company_id),
            name=normalized_name,
            bank_name=normalized_bank_name,
            currency_code=currency_code.upper(),
            status="active",
            created_by_user_id=actor_user_id,
        )
        self._db.add(record)
        self._db.commit()
        self._db.refresh(record)
        return record

    def list_accounts(self, company_id: UUID) -> tuple[BankAccountRecord, ...]:
        return tuple(
            self._db.scalars(
                select(BankAccountRecord)
                .where(BankAccountRecord.company_id == str(company_id))
                .order_by(BankAccountRecord.status.asc(), BankAccountRecord.name.asc())
            )
        )

    def import_csv(
        self,
        company_id: UUID,
        bank_account_id: UUID,
        content: bytes,
        *,
        actor_user_id: int,
    ) -> BankImportResult:
        account = self._account(company_id, bank_account_id, require_active=True)
        text = self._decode(content)
        reader = self._reader(text)
        fields = self._resolve_fields(reader.fieldnames or [])
        import_record = BankStatementImportRecord(
            id=str(uuid4()),
            company_id=str(company_id),
            bank_account_id=str(bank_account_id),
            accepted_rows=0,
            rejected_rows=0,
            duplicate_rows=0,
            created_by_user_id=actor_user_id,
        )
        self._db.add(import_record)
        self._db.flush()

        accepted = 0
        duplicates = 0
        rejections: list[BankImportRejection] = []
        for row_number, row in enumerate(reader, start=2):
            try:
                transaction_date = self._parse_date(row.get(fields["date"], ""))
                amount = self._parse_amount(row.get(fields["amount"], ""))
                currency = (
                    row.get(fields.get("currency", ""), "") or account.currency_code
                ).strip().upper()
                if currency != account.currency_code:
                    raise ValueError(
                        "La moneda de la fila no coincide con la moneda de la cuenta."
                    )
                description = self._optional(row.get(fields.get("description", "")), 280)
                reference = self._optional(row.get(fields.get("reference", "")), 100)
                fingerprint = self._fingerprint(
                    bank_account_id,
                    transaction_date,
                    amount,
                    currency,
                    reference,
                    description,
                    row_number if reference is None else None,
                )
                if self._fingerprint_exists(bank_account_id, fingerprint):
                    duplicates += 1
                    continue
                transaction = BankTransactionRecord(
                    id=str(uuid4()),
                    company_id=str(company_id),
                    bank_account_id=str(bank_account_id),
                    import_id=import_record.id,
                    transaction_date=transaction_date,
                    amount=amount,
                    currency_code=currency,
                    description=description,
                    reference=reference,
                    fingerprint=fingerprint,
                    status="pending",
                    match_candidate_count=0,
                    created_by_user_id=actor_user_id,
                )
                self._db.add(transaction)
                self._db.flush()
                self._suggest(transaction)
                accepted += 1
            except (InvalidOperation, ValueError) as exc:
                rejections.append(
                    BankImportRejection(row_number=row_number, message=str(exc)[:500])
                )

        import_record.accepted_rows = accepted
        import_record.rejected_rows = len(rejections)
        import_record.duplicate_rows = duplicates
        self._db.commit()
        return BankImportResult(
            import_id=UUID(import_record.id),
            accepted_rows=accepted,
            duplicate_rows=duplicates,
            rejections=tuple(rejections),
        )

    def list_transactions(
        self,
        company_id: UUID,
        *,
        bank_account_id: UUID | None,
        status: str | None,
        limit: int,
        offset: int,
    ) -> BankTransactionPage:
        filters = [BankTransactionRecord.company_id == str(company_id)]
        if bank_account_id is not None:
            filters.append(BankTransactionRecord.bank_account_id == str(bank_account_id))
        if status is not None:
            filters.append(BankTransactionRecord.status == status)
        total = int(
            self._db.scalar(
                select(func.count(BankTransactionRecord.id)).where(*filters)
            )
            or 0
        )
        rows = self._db.execute(
            select(BankTransactionRecord, PaymentRecord.payment_date)
            .outerjoin(
                PaymentRecord,
                PaymentRecord.id == BankTransactionRecord.suggested_payment_id,
            )
            .where(*filters)
            .order_by(
                BankTransactionRecord.transaction_date.desc(),
                BankTransactionRecord.created_at.desc(),
            )
            .offset(offset)
            .limit(limit)
        ).all()
        return BankTransactionPage(
            total=total,
            items=tuple(self._item(record, payment_date) for record, payment_date in rows),
        )

    def review(
        self,
        company_id: UUID,
        transaction_id: UUID,
        *,
        action: str,
        actor_user_id: int,
    ) -> BankTransactionRecord:
        record = self._db.scalar(
            select(BankTransactionRecord).where(
                BankTransactionRecord.id == str(transaction_id),
                BankTransactionRecord.company_id == str(company_id),
            )
        )
        if record is None:
            raise app_error(
                "NOT_FOUND", message="Movimiento bancario no encontrado para esta empresa."
            )

        if action == "confirm":
            if record.status != "suggested" or record.suggested_payment_id is None:
                raise app_error(
                    "CONFLICT",
                    message="El movimiento no tiene una coincidencia única pendiente de confirmación.",
                )
            already_used = self._db.scalar(
                select(BankTransactionRecord.id).where(
                    BankTransactionRecord.matched_payment_id
                    == record.suggested_payment_id,
                    BankTransactionRecord.id != record.id,
                )
            )
            if already_used is not None:
                raise app_error(
                    "CONFLICT", message="El pago sugerido ya fue conciliado."
                )
            record.matched_payment_id = record.suggested_payment_id
            record.status = "reconciled"
        elif action == "dismiss":
            if record.status != "suggested":
                raise app_error(
                    "CONFLICT", message="Sólo se puede descartar una sugerencia activa."
                )
            record.status = "dismissed"
            record.suggested_payment_id = None
        elif action == "exclude":
            if record.status == "reconciled":
                raise app_error(
                    "CONFLICT",
                    message="Reabre la conciliación antes de excluir el movimiento.",
                )
            record.status = "excluded"
            record.suggested_payment_id = None
            record.matched_payment_id = None
        elif action == "reopen":
            if record.status not in {"reconciled", "dismissed", "excluded"}:
                raise app_error(
                    "CONFLICT", message="El movimiento ya está pendiente de revisión."
                )
            record.status = "pending"
            record.suggested_payment_id = None
            record.matched_payment_id = None
            record.match_candidate_count = 0
        else:
            raise app_error("VALIDATION_ERROR", message="Acción de revisión no válida.")

        record.reviewed_by_user_id = actor_user_id
        record.reviewed_at = datetime.now(UTC).replace(tzinfo=None)
        if action in {"confirm", "reopen"}:
            self._db.flush()
            self._refresh_open_suggestions(record.company_id)
        self._db.commit()
        self._db.refresh(record)
        return record

    def _suggest(self, transaction: BankTransactionRecord) -> None:
        invoice_type = "sale" if Decimal(transaction.amount) > 0 else "purchase"
        amount = abs(Decimal(transaction.amount)).quantize(_CENT)
        start = transaction.transaction_date - timedelta(days=3)
        end = transaction.transaction_date + timedelta(days=3)
        matched_payments = select(BankTransactionRecord.matched_payment_id).where(
            BankTransactionRecord.matched_payment_id.is_not(None)
        )
        candidates = list(
            self._db.scalars(
                select(PaymentRecord.id)
                .join(InvoiceRecord, InvoiceRecord.id == PaymentRecord.invoice_id)
                .where(
                    PaymentRecord.company_id == transaction.company_id,
                    PaymentRecord.currency_code == transaction.currency_code,
                    PaymentRecord.amount == amount,
                    PaymentRecord.payment_date.between(start, end),
                    InvoiceRecord.invoice_type == invoice_type,
                    PaymentRecord.id.not_in(matched_payments),
                )
                .order_by(PaymentRecord.payment_date.asc(), PaymentRecord.id.asc())
            )
        )
        transaction.match_candidate_count = len(candidates)
        if len(candidates) == 1:
            transaction.status = "suggested"
            transaction.suggested_payment_id = candidates[0]
        else:
            transaction.status = "pending"
            transaction.suggested_payment_id = None

    def _refresh_open_suggestions(self, company_id: str) -> None:
        records = tuple(
            self._db.scalars(
                select(BankTransactionRecord).where(
                    BankTransactionRecord.company_id == company_id,
                    BankTransactionRecord.status.in_(("pending", "suggested")),
                )
            )
        )
        for record in records:
            record.status = "pending"
            record.match_candidate_count = 0
            record.suggested_payment_id = None
        self._db.flush()
        for record in records:
            self._suggest(record)

    def _account(
        self,
        company_id: UUID,
        account_id: UUID,
        *,
        require_active: bool,
    ) -> BankAccountRecord:
        filters = [
            BankAccountRecord.id == str(account_id),
            BankAccountRecord.company_id == str(company_id),
        ]
        if require_active:
            filters.append(BankAccountRecord.status == "active")
        record = self._db.scalar(select(BankAccountRecord).where(*filters))
        if record is None:
            raise app_error(
                "NOT_FOUND", message="Cuenta bancaria activa no encontrada para esta empresa."
            )
        return record

    @staticmethod
    def _decode(content: bytes) -> str:
        try:
            return content.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise app_error(
                "VALIDATION_ERROR", message="El extracto CSV debe usar codificación UTF-8."
            ) from exc

    @staticmethod
    def _reader(text: str) -> csv.DictReader:
        if not text.strip():
            raise app_error("VALIDATION_ERROR", message="El archivo está vacío.")
        try:
            dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;")
        except csv.Error:
            dialect = csv.excel
        return csv.DictReader(StringIO(text), dialect=dialect)

    @staticmethod
    def _resolve_fields(headers: list[str]) -> dict[str, str]:
        normalized = {header.strip().casefold(): header for header in headers if header}
        resolved: dict[str, str] = {}
        for field, aliases in _FIELD_ALIASES.items():
            match = next((normalized[alias] for alias in aliases if alias in normalized), None)
            if match is not None:
                resolved[field] = match
        if "date" not in resolved or "amount" not in resolved:
            raise app_error(
                "VALIDATION_ERROR",
                message="El CSV debe incluir las columnas fecha/date y valor/amount.",
            )
        return resolved

    @staticmethod
    def _parse_date(value: str | None) -> date:
        normalized = (value or "").strip()
        for pattern in _DATE_FORMATS:
            try:
                return datetime.strptime(normalized, pattern).date()
            except ValueError:
                continue
        raise ValueError("La fecha debe usar AAAA-MM-DD o DD/MM/AAAA.")

    @staticmethod
    def _parse_amount(value: str | None) -> Decimal:
        normalized = (value or "").strip().replace("$", "").replace(" ", "")
        if not normalized:
            raise ValueError("El valor es obligatorio.")
        if "," in normalized and "." in normalized:
            if normalized.rfind(",") > normalized.rfind("."):
                normalized = normalized.replace(".", "").replace(",", ".")
            else:
                normalized = normalized.replace(",", "")
        elif "," in normalized:
            normalized = normalized.replace(",", ".")
        amount = Decimal(normalized).quantize(_CENT)
        if not amount.is_finite() or amount == 0:
            raise ValueError("El valor del movimiento no puede ser cero.")
        return amount

    @staticmethod
    def _optional(value: str | None, maximum: int) -> str | None:
        normalized = (value or "").strip()
        if len(normalized) > maximum:
            raise ValueError(
                f"Un campo de texto supera el máximo permitido de {maximum} caracteres."
            )
        return normalized or None

    @staticmethod
    def _fingerprint(
        account_id: UUID,
        transaction_date: date,
        amount: Decimal,
        currency: str,
        reference: str | None,
        description: str | None,
        ordinal: int | None,
    ) -> str:
        source = "|".join(
            (
                str(account_id),
                transaction_date.isoformat(),
                str(amount),
                currency,
                (reference or "").casefold(),
                (description or "").casefold(),
                str(ordinal or ""),
            )
        )
        return sha256(source.encode()).hexdigest()

    def _fingerprint_exists(self, account_id: UUID, fingerprint: str) -> bool:
        return (
            self._db.scalar(
                select(BankTransactionRecord.id).where(
                    BankTransactionRecord.bank_account_id == str(account_id),
                    BankTransactionRecord.fingerprint == fingerprint,
                )
            )
            is not None
        )

    @staticmethod
    def _item(record: BankTransactionRecord, payment_date: date | None) -> BankTransactionItem:
        return BankTransactionItem(
            id=UUID(record.id),
            bank_account_id=UUID(record.bank_account_id),
            transaction_date=record.transaction_date,
            amount=Decimal(record.amount).quantize(_CENT),
            currency_code=record.currency_code,
            description=record.description,
            reference=record.reference,
            status=record.status,
            match_candidate_count=record.match_candidate_count,
            suggested_payment_id=(
                UUID(record.suggested_payment_id) if record.suggested_payment_id else None
            ),
            suggested_payment_date=payment_date,
            matched_payment_id=(
                UUID(record.matched_payment_id) if record.matched_payment_id else None
            ),
            reviewed_by_user_id=record.reviewed_by_user_id,
            reviewed_at=record.reviewed_at,
        )
