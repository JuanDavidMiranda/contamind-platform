"""Persistencia del núcleo contable capturado desde fuentes manuales."""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, Index, Integer, JSON, Numeric, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class TaxRecord(Base):
    __tablename__ = "taxes"
    __table_args__ = (
        UniqueConstraint("company_id", "data_source_id", "idempotency_key", name="uq_taxes_source_idempotency"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.id"), index=True)
    data_source_id: Mapped[str] = mapped_column(ForeignKey("company_data_sources.id"), index=True)
    code: Mapped[str] = mapped_column(String(50))
    name: Mapped[str] = mapped_column(String(100))
    rate: Mapped[Decimal] = mapped_column(Numeric(7, 4))
    idempotency_key: Mapped[str] = mapped_column(String(128))
    created_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class ItemRecord(Base):
    __tablename__ = "items"
    __table_args__ = (
        UniqueConstraint("company_id", "data_source_id", "idempotency_key", name="uq_items_source_idempotency"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.id"), index=True)
    data_source_id: Mapped[str] = mapped_column(ForeignKey("company_data_sources.id"), index=True)
    code: Mapped[str] = mapped_column(String(100))
    name: Mapped[str] = mapped_column(String(255))
    item_type: Mapped[str] = mapped_column(String(20))
    unit: Mapped[str | None] = mapped_column(String(50), nullable=True)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    tax_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    ledger_account: Mapped[str | None] = mapped_column(String(100), nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(128))
    created_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class InvoiceRecord(Base):
    __tablename__ = "invoices"
    __table_args__ = (
        UniqueConstraint("company_id", "data_source_id", "idempotency_key", name="uq_invoices_source_idempotency"),
        CheckConstraint(
            "due_date IS NULL OR due_date >= issue_date",
            name="ck_invoices_due_date_on_or_after_issue",
        ),
        CheckConstraint(
            "payment_terms_days IS NULL OR payment_terms_days BETWEEN 0 AND 3650",
            name="ck_invoices_payment_terms_days_range",
        ),
        Index("ix_invoices_company_type_due_date", "company_id", "invoice_type", "due_date"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.id"), index=True)
    data_source_id: Mapped[str] = mapped_column(ForeignKey("company_data_sources.id"), index=True)
    invoice_type: Mapped[str] = mapped_column(String(30))
    issue_date: Mapped[date] = mapped_column(Date)
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    payment_terms_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    issuer_party_id: Mapped[str | None] = mapped_column(ForeignKey("parties.id"), nullable=True)
    recipient_party_id: Mapped[str | None] = mapped_column(ForeignKey("parties.id"), nullable=True)
    currency_code: Mapped[str] = mapped_column(String(3))
    exchange_rate: Mapped[Decimal] = mapped_column(Numeric(18, 6))
    currency_as_of: Mapped[date | None] = mapped_column(Date, nullable=True)
    subtotal: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    tax_total: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    withholding_total: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    total: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    number: Mapped[str | None] = mapped_column(String(100), nullable=True)
    status: Mapped[str | None] = mapped_column(String(50), nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(128))
    created_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    updated_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class InvoiceLineRecord(Base):
    __tablename__ = "invoice_lines"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    invoice_id: Mapped[str] = mapped_column(ForeignKey("invoices.id", ondelete="CASCADE"), index=True)
    item_id: Mapped[str | None] = mapped_column(ForeignKey("items.id"), nullable=True)
    description: Mapped[str] = mapped_column(String(500))
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 6))
    unit_price: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    tax_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    withholding_ids: Mapped[list[str]] = mapped_column(JSON, default=list)


class PaymentRecord(Base):
    __tablename__ = "payments"
    __table_args__ = (
        UniqueConstraint("company_id", "data_source_id", "idempotency_key", name="uq_payments_source_idempotency"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.id"), index=True)
    data_source_id: Mapped[str] = mapped_column(ForeignKey("company_data_sources.id"), index=True)
    payment_date: Mapped[date] = mapped_column(Date)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    currency_code: Mapped[str] = mapped_column(String(3))
    exchange_rate: Mapped[Decimal] = mapped_column(Numeric(18, 6))
    currency_as_of: Mapped[date | None] = mapped_column(Date, nullable=True)
    invoice_id: Mapped[str | None] = mapped_column(ForeignKey("invoices.id"), nullable=True)
    payment_method: Mapped[str | None] = mapped_column(String(100), nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(128))
    created_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class JournalEntryRecord(Base):
    __tablename__ = "journal_entries"
    __table_args__ = (
        UniqueConstraint("company_id", "data_source_id", "idempotency_key", name="uq_journal_entries_source_idempotency"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.id"), index=True)
    data_source_id: Mapped[str] = mapped_column(ForeignKey("company_data_sources.id"), index=True)
    entry_date: Mapped[date] = mapped_column(Date)
    description: Mapped[str] = mapped_column(String(500))
    source_reference: Mapped[str | None] = mapped_column(String(255), nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(128))
    created_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class JournalEntryLineRecord(Base):
    __tablename__ = "journal_entry_lines"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    journal_entry_id: Mapped[str] = mapped_column(
        ForeignKey("journal_entries.id", ondelete="CASCADE"), index=True
    )
    account_code: Mapped[str] = mapped_column(String(100))
    debit: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    credit: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    party_id: Mapped[str | None] = mapped_column(ForeignKey("parties.id"), nullable=True)
    cost_center: Mapped[str | None] = mapped_column(String(100), nullable=True)
