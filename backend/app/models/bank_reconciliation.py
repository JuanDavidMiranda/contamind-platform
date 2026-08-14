"""Persistencia de extractos y decisiones de conciliación bancaria."""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class BankAccountRecord(Base):
    __tablename__ = "bank_accounts"
    __table_args__ = (
        UniqueConstraint("company_id", "name", name="uq_bank_accounts_company_name"),
        CheckConstraint("status IN ('active', 'disabled')", name="ck_bank_accounts_status"),
        Index("ix_bank_accounts_company_status", "company_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    company_id: Mapped[str] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(100))
    bank_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    currency_code: Mapped[str] = mapped_column(String(3))
    status: Mapped[str] = mapped_column(String(20), default="active", index=True)
    created_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class BankBalanceSnapshotRecord(Base):
    """Corte manual y verificado de saldo, inmutable para conservar trazabilidad."""

    __tablename__ = "bank_balance_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "bank_account_id",
            "as_of_date",
            name="uq_bank_balance_snapshots_account_date",
        ),
        Index(
            "ix_bank_balance_snapshots_company_date",
            "company_id",
            "as_of_date",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    company_id: Mapped[str] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), index=True
    )
    bank_account_id: Mapped[str] = mapped_column(
        ForeignKey("bank_accounts.id", ondelete="CASCADE"), index=True
    )
    as_of_date: Mapped[date] = mapped_column(Date)
    balance: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    currency_code: Mapped[str] = mapped_column(String(3))
    verified_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    verified_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class BankStatementImportRecord(Base):
    __tablename__ = "bank_statement_imports"
    __table_args__ = (
        Index("ix_bank_statement_imports_company_created", "company_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    company_id: Mapped[str] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), index=True
    )
    bank_account_id: Mapped[str] = mapped_column(
        ForeignKey("bank_accounts.id", ondelete="CASCADE"), index=True
    )
    accepted_rows: Mapped[int] = mapped_column(Integer, default=0)
    rejected_rows: Mapped[int] = mapped_column(Integer, default=0)
    duplicate_rows: Mapped[int] = mapped_column(Integer, default=0)
    created_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class BankTransactionRecord(Base):
    __tablename__ = "bank_transactions"
    __table_args__ = (
        UniqueConstraint(
            "bank_account_id",
            "fingerprint",
            name="uq_bank_transactions_account_fingerprint",
        ),
        UniqueConstraint("matched_payment_id", name="uq_bank_transactions_matched_payment"),
        CheckConstraint("amount != 0", name="ck_bank_transactions_non_zero_amount"),
        CheckConstraint(
            "status IN ('pending', 'suggested', 'reconciled', 'dismissed', 'excluded')",
            name="ck_bank_transactions_status",
        ),
        CheckConstraint("match_candidate_count >= 0", name="ck_bank_transactions_candidates"),
        Index("ix_bank_transactions_company_status", "company_id", "status"),
        Index(
            "ix_bank_transactions_account_date",
            "bank_account_id",
            "transaction_date",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    company_id: Mapped[str] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), index=True
    )
    bank_account_id: Mapped[str] = mapped_column(
        ForeignKey("bank_accounts.id", ondelete="CASCADE"), index=True
    )
    import_id: Mapped[str] = mapped_column(
        ForeignKey("bank_statement_imports.id", ondelete="CASCADE"), index=True
    )
    transaction_date: Mapped[date] = mapped_column(Date)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    currency_code: Mapped[str] = mapped_column(String(3))
    description: Mapped[str | None] = mapped_column(String(280), nullable=True)
    reference: Mapped[str | None] = mapped_column(String(100), nullable=True)
    fingerprint: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    match_candidate_count: Mapped[int] = mapped_column(Integer, default=0)
    suggested_payment_id: Mapped[str | None] = mapped_column(
        ForeignKey("payments.id"), nullable=True, index=True
    )
    matched_payment_id: Mapped[str | None] = mapped_column(
        ForeignKey("payments.id"), nullable=True, index=True
    )
    created_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    reviewed_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True, index=True
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )
