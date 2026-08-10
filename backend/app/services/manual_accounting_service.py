"""Captura manual idempotente del núcleo contable canónico."""

from decimal import Decimal, ROUND_HALF_UP
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.data_sources.models import ConnectionMode, DataCapability, DataSourceKind, DataSourceStatus
from app.models.accounting import (
    InvoiceLineRecord,
    InvoiceRecord,
    ItemRecord,
    JournalEntryLineRecord,
    JournalEntryRecord,
    PaymentRecord,
    TaxRecord,
)
from app.models.data_source import PartyRecord
from app.providers.canonical import (
    Currency,
    Invoice,
    InvoiceLine,
    InvoiceType,
    Item,
    ItemType,
    JournalEntry,
    JournalEntryLine,
    Payment,
    Tax,
)
from app.services.data_source_service import DataSourceService
from app.shared.errors import app_error

_CENT = Decimal("0.01")


class ManualAccountingService:
    def __init__(self, db: Session) -> None:
        self._db = db

    def create_tax(
        self,
        data_source_id: UUID,
        *,
        code: str,
        name: str,
        rate: Decimal,
        actor_user_id: int,
        idempotency_key: str,
    ) -> Tax:
        idempotency_key = self._normalize_idempotency_key(idempotency_key)
        source = self._manual_source(data_source_id, DataCapability.TAXES)
        existing = self._idempotent(TaxRecord, source.id, source.company_id, idempotency_key)
        if existing is not None:
            return self._tax_from_record(existing)
        tax = Tax(company_id=source.company_id, code=code, name=name, rate=rate)
        self._db.add(
            TaxRecord(
                id=str(tax.id),
                company_id=str(tax.company_id),
                data_source_id=str(source.id),
                code=tax.code,
                name=tax.name,
                rate=tax.rate,
                idempotency_key=idempotency_key,
                created_by_user_id=actor_user_id,
            )
        )
        self._db.commit()
        return tax

    def create_item(
        self,
        data_source_id: UUID,
        *,
        code: str,
        name: str,
        item_type: ItemType,
        unit: str | None,
        unit_price: Decimal,
        tax_ids: tuple[UUID, ...],
        ledger_account: str | None,
        actor_user_id: int,
        idempotency_key: str,
    ) -> Item:
        idempotency_key = self._normalize_idempotency_key(idempotency_key)
        source = self._manual_source(data_source_id, DataCapability.ITEMS)
        existing = self._idempotent(ItemRecord, source.id, source.company_id, idempotency_key)
        if existing is not None:
            return self._item_from_record(existing)
        self._ensure_ids(TaxRecord, source.company_id, tax_ids, "impuesto")
        item = Item(
            company_id=source.company_id,
            code=code,
            name=name,
            item_type=item_type,
            unit=unit,
            unit_price=self._money(unit_price),
            tax_ids=tax_ids,
            ledger_account=ledger_account,
        )
        self._db.add(
            ItemRecord(
                id=str(item.id),
                company_id=str(item.company_id),
                data_source_id=str(source.id),
                code=item.code,
                name=item.name,
                item_type=item.item_type.value,
                unit=item.unit,
                unit_price=item.unit_price,
                tax_ids=[str(tax_id) for tax_id in item.tax_ids],
                ledger_account=item.ledger_account,
                idempotency_key=idempotency_key,
                created_by_user_id=actor_user_id,
            )
        )
        self._db.commit()
        return item

    def create_invoice(
        self,
        data_source_id: UUID,
        *,
        invoice_type: InvoiceType,
        issue_date,
        issuer_party_id: UUID | None,
        recipient_party_id: UUID | None,
        lines: tuple[InvoiceLine, ...],
        currency: Currency,
        tax_total: Decimal,
        withholding_total: Decimal,
        number: str | None,
        status: str | None,
        actor_user_id: int,
        idempotency_key: str,
    ) -> Invoice:
        idempotency_key = self._normalize_idempotency_key(idempotency_key)
        source = self._manual_source(data_source_id, DataCapability.INVOICES)
        existing = self._idempotent(InvoiceRecord, source.id, source.company_id, idempotency_key)
        if existing is not None:
            return self._invoice_from_record(existing)
        self._ensure_ids(PartyRecord, source.company_id, self._present_ids(issuer_party_id, recipient_party_id), "tercero")
        self._ensure_ids(
            ItemRecord,
            source.company_id,
            tuple(line.item_id for line in lines if line.item_id is not None),
            "ítem",
        )
        self._ensure_ids(
            TaxRecord,
            source.company_id,
            tuple(tax_id for line in lines for tax_id in (*line.tax_ids, *line.withholding_ids)),
            "impuesto",
        )
        subtotal = self._money(sum((line.quantity * line.unit_price for line in lines), Decimal("0")))
        tax_total = self._money(tax_total)
        withholding_total = self._money(withholding_total)
        total = self._money(subtotal + tax_total - withholding_total)
        if total < 0:
            raise app_error("VALIDATION_ERROR", message="El total de la factura no puede ser negativo.")
        invoice = Invoice(
            company_id=source.company_id,
            invoice_type=invoice_type,
            issue_date=issue_date,
            issuer_party_id=issuer_party_id,
            recipient_party_id=recipient_party_id,
            lines=lines,
            currency=currency,
            subtotal=subtotal,
            tax_total=tax_total,
            withholding_total=withholding_total,
            total=total,
            number=number,
            status=status,
        )
        self._db.add(
            InvoiceRecord(
                id=str(invoice.id),
                company_id=str(invoice.company_id),
                data_source_id=str(source.id),
                invoice_type=invoice.invoice_type.value,
                issue_date=invoice.issue_date,
                issuer_party_id=str(invoice.issuer_party_id) if invoice.issuer_party_id else None,
                recipient_party_id=str(invoice.recipient_party_id) if invoice.recipient_party_id else None,
                currency_code=invoice.currency.code,
                exchange_rate=invoice.currency.exchange_rate,
                currency_as_of=invoice.currency.as_of,
                subtotal=invoice.subtotal,
                tax_total=invoice.tax_total,
                withholding_total=invoice.withholding_total,
                total=invoice.total,
                number=invoice.number,
                status=invoice.status,
                idempotency_key=idempotency_key,
                created_by_user_id=actor_user_id,
            )
        )
        for line in invoice.lines:
            self._db.add(
                InvoiceLineRecord(
                    id=str(uuid4()),
                    invoice_id=str(invoice.id),
                    item_id=str(line.item_id) if line.item_id else None,
                    description=line.description,
                    quantity=line.quantity,
                    unit_price=self._money(line.unit_price),
                    tax_ids=[str(tax_id) for tax_id in line.tax_ids],
                    withholding_ids=[str(tax_id) for tax_id in line.withholding_ids],
                )
            )
        self._db.commit()
        return invoice

    def create_payment(
        self,
        data_source_id: UUID,
        *,
        payment_date,
        amount: Decimal,
        currency: Currency,
        invoice_id: UUID | None,
        payment_method: str | None,
        actor_user_id: int,
        idempotency_key: str,
    ) -> Payment:
        idempotency_key = self._normalize_idempotency_key(idempotency_key)
        source = self._manual_source(data_source_id, DataCapability.PAYMENTS)
        existing = self._idempotent(PaymentRecord, source.id, source.company_id, idempotency_key)
        if existing is not None:
            return self._payment_from_record(existing)
        self._ensure_ids(InvoiceRecord, source.company_id, self._present_ids(invoice_id), "factura")
        payment = Payment(
            company_id=source.company_id,
            payment_date=payment_date,
            amount=self._money(amount),
            currency=currency,
            invoice_id=invoice_id,
            payment_method=payment_method,
        )
        self._db.add(
            PaymentRecord(
                id=str(payment.id),
                company_id=str(payment.company_id),
                data_source_id=str(source.id),
                payment_date=payment.payment_date,
                amount=payment.amount,
                currency_code=payment.currency.code,
                exchange_rate=payment.currency.exchange_rate,
                currency_as_of=payment.currency.as_of,
                invoice_id=str(payment.invoice_id) if payment.invoice_id else None,
                payment_method=payment.payment_method,
                idempotency_key=idempotency_key,
                created_by_user_id=actor_user_id,
            )
        )
        self._db.commit()
        return payment

    def create_journal_entry(
        self,
        data_source_id: UUID,
        *,
        entry_date,
        description: str,
        lines: tuple[JournalEntryLine, ...],
        source_reference: str | None,
        actor_user_id: int,
        idempotency_key: str,
    ) -> JournalEntry:
        idempotency_key = self._normalize_idempotency_key(idempotency_key)
        source = self._manual_source(data_source_id, DataCapability.JOURNALS)
        existing = self._idempotent(JournalEntryRecord, source.id, source.company_id, idempotency_key)
        if existing is not None:
            return self._journal_from_record(existing)
        debit = self._money(sum((line.debit for line in lines), Decimal("0")))
        credit = self._money(sum((line.credit for line in lines), Decimal("0")))
        if debit <= 0 or debit != credit or any(line.debit > 0 and line.credit > 0 for line in lines):
            raise app_error(
                "VALIDATION_ERROR",
                message="El comprobante debe cuadrar y cada línea debe ser débito o crédito, no ambos.",
            )
        self._ensure_ids(
            PartyRecord,
            source.company_id,
            tuple(line.party_id for line in lines if line.party_id is not None),
            "tercero",
        )
        entry = JournalEntry(
            company_id=source.company_id,
            entry_date=entry_date,
            description=description,
            lines=lines,
            source_reference=source_reference,
        )
        self._db.add(
            JournalEntryRecord(
                id=str(entry.id),
                company_id=str(entry.company_id),
                data_source_id=str(source.id),
                entry_date=entry.entry_date,
                description=entry.description,
                source_reference=entry.source_reference,
                idempotency_key=idempotency_key,
                created_by_user_id=actor_user_id,
            )
        )
        for line in entry.lines:
            self._db.add(
                JournalEntryLineRecord(
                    id=str(uuid4()),
                    journal_entry_id=str(entry.id),
                    account_code=line.account_code,
                    debit=self._money(line.debit),
                    credit=self._money(line.credit),
                    party_id=str(line.party_id) if line.party_id else None,
                    cost_center=line.cost_center,
                )
            )
        self._db.commit()
        return entry

    def _manual_source(self, data_source_id: UUID, capability: DataCapability):
        source = DataSourceService(self._db).get_source(data_source_id)
        allowed_source = (
            source.kind is DataSourceKind.MANUAL_ENTRY and source.mode is ConnectionMode.MANUAL
        ) or (
            source.kind is DataSourceKind.FILE_IMPORT and source.mode is ConnectionMode.FILE_UPLOAD
        )
        if not allowed_source or source.status is not DataSourceStatus.ACTIVE:
            raise app_error("CONFLICT", message="La fuente no está disponible para esta captura contable.")
        if capability not in source.capabilities:
            raise app_error(
                "CONFLICT",
                message="La fuente no tiene habilitada esta capacidad contable.",
                details={"capability": capability.value},
            )
        return source

    def _idempotent(self, model, data_source_id: UUID, company_id: UUID, key: str):
        return self._db.scalar(
            select(model).where(
                model.data_source_id == str(data_source_id),
                model.company_id == str(company_id),
                model.idempotency_key == key,
            )
        )

    @staticmethod
    def _normalize_idempotency_key(value: str) -> str:
        normalized = value.strip()
        if not normalized or len(normalized) > 128:
            raise app_error(
                "VALIDATION_ERROR",
                message="Idempotency-Key es obligatorio y debe tener máximo 128 caracteres.",
            )
        return normalized

    def _ensure_ids(self, model, company_id: UUID, ids: tuple[UUID, ...], label: str) -> None:
        if not ids:
            return
        unique_ids = {str(value) for value in ids}
        found = set(
            self._db.scalars(
                select(model.id).where(model.company_id == str(company_id), model.id.in_(unique_ids))
            )
        )
        if found != unique_ids:
            raise app_error(
                "VALIDATION_ERROR",
                message=f"Uno o más {label}s no pertenecen a la empresa.",
            )

    @staticmethod
    def _present_ids(*values: UUID | None) -> tuple[UUID, ...]:
        return tuple(value for value in values if value is not None)

    @staticmethod
    def _money(value: Decimal) -> Decimal:
        return value.quantize(_CENT, rounding=ROUND_HALF_UP)

    @staticmethod
    def _tax_from_record(record: TaxRecord) -> Tax:
        return Tax(
            id=UUID(record.id),
            company_id=UUID(record.company_id),
            code=record.code,
            name=record.name,
            rate=record.rate,
        )

    @staticmethod
    def _item_from_record(record: ItemRecord) -> Item:
        return Item(
            id=UUID(record.id),
            company_id=UUID(record.company_id),
            code=record.code,
            name=record.name,
            item_type=record.item_type,
            unit=record.unit,
            unit_price=record.unit_price,
            tax_ids=tuple(UUID(value) for value in record.tax_ids),
            ledger_account=record.ledger_account,
        )

    def _invoice_from_record(self, record: InvoiceRecord) -> Invoice:
        lines = tuple(
            InvoiceLine(
                item_id=UUID(line.item_id) if line.item_id else None,
                description=line.description,
                quantity=line.quantity,
                unit_price=line.unit_price,
                tax_ids=tuple(UUID(value) for value in line.tax_ids),
                withholding_ids=tuple(UUID(value) for value in line.withholding_ids),
            )
            for line in self._db.scalars(
                select(InvoiceLineRecord).where(InvoiceLineRecord.invoice_id == record.id)
            )
        )
        return Invoice(
            id=UUID(record.id),
            company_id=UUID(record.company_id),
            invoice_type=record.invoice_type,
            issue_date=record.issue_date,
            issuer_party_id=UUID(record.issuer_party_id) if record.issuer_party_id else None,
            recipient_party_id=UUID(record.recipient_party_id) if record.recipient_party_id else None,
            lines=lines,
            currency=Currency(code=record.currency_code, exchange_rate=record.exchange_rate, as_of=record.currency_as_of),
            subtotal=record.subtotal,
            tax_total=record.tax_total,
            withholding_total=record.withholding_total,
            total=record.total,
            number=record.number,
            status=record.status,
        )

    @staticmethod
    def _payment_from_record(record: PaymentRecord) -> Payment:
        return Payment(
            id=UUID(record.id),
            company_id=UUID(record.company_id),
            payment_date=record.payment_date,
            amount=record.amount,
            currency=Currency(code=record.currency_code, exchange_rate=record.exchange_rate, as_of=record.currency_as_of),
            invoice_id=UUID(record.invoice_id) if record.invoice_id else None,
            payment_method=record.payment_method,
        )

    def _journal_from_record(self, record: JournalEntryRecord) -> JournalEntry:
        lines = tuple(
            JournalEntryLine(
                account_code=line.account_code,
                debit=line.debit,
                credit=line.credit,
                party_id=UUID(line.party_id) if line.party_id else None,
                cost_center=line.cost_center,
            )
            for line in self._db.scalars(
                select(JournalEntryLineRecord).where(JournalEntryLineRecord.journal_entry_id == record.id)
            )
        )
        return JournalEntry(
            id=UUID(record.id),
            company_id=UUID(record.company_id),
            entry_date=record.entry_date,
            description=record.description,
            lines=lines,
            source_reference=record.source_reference,
        )
