"""add manual accounting core

Revision ID: f2b6d8c4a1e9
Revises: e7c3f9b1a4d6
Create Date: 2026-08-10 15:10:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f2b6d8c4a1e9"
down_revision: Union[str, Sequence[str], None] = "e7c3f9b1a4d6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "taxes",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("company_id", sa.String(length=36), nullable=False),
        sa.Column("data_source_id", sa.String(length=36), nullable=False),
        sa.Column("code", sa.String(length=50), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("rate", sa.Numeric(precision=7, scale=4), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("created_by_user_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"]),
        sa.ForeignKeyConstraint(["data_source_id"], ["company_data_sources.id"]),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("company_id", "data_source_id", "idempotency_key", name="uq_taxes_source_idempotency"),
    )
    op.create_index("ix_taxes_company_id", "taxes", ["company_id"])
    op.create_index("ix_taxes_data_source_id", "taxes", ["data_source_id"])
    op.create_index("ix_taxes_created_by_user_id", "taxes", ["created_by_user_id"])

    op.create_table(
        "items",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("company_id", sa.String(length=36), nullable=False),
        sa.Column("data_source_id", sa.String(length=36), nullable=False),
        sa.Column("code", sa.String(length=100), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("item_type", sa.String(length=20), nullable=False),
        sa.Column("unit", sa.String(length=50), nullable=True),
        sa.Column("unit_price", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("tax_ids", sa.JSON(), nullable=False),
        sa.Column("ledger_account", sa.String(length=100), nullable=True),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("created_by_user_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"]),
        sa.ForeignKeyConstraint(["data_source_id"], ["company_data_sources.id"]),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("company_id", "data_source_id", "idempotency_key", name="uq_items_source_idempotency"),
    )
    op.create_index("ix_items_company_id", "items", ["company_id"])
    op.create_index("ix_items_data_source_id", "items", ["data_source_id"])
    op.create_index("ix_items_created_by_user_id", "items", ["created_by_user_id"])

    op.create_table(
        "invoices",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("company_id", sa.String(length=36), nullable=False),
        sa.Column("data_source_id", sa.String(length=36), nullable=False),
        sa.Column("invoice_type", sa.String(length=30), nullable=False),
        sa.Column("issue_date", sa.Date(), nullable=False),
        sa.Column("issuer_party_id", sa.String(length=36), nullable=True),
        sa.Column("recipient_party_id", sa.String(length=36), nullable=True),
        sa.Column("currency_code", sa.String(length=3), nullable=False),
        sa.Column("exchange_rate", sa.Numeric(precision=18, scale=6), nullable=False),
        sa.Column("currency_as_of", sa.Date(), nullable=True),
        sa.Column("subtotal", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("tax_total", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("withholding_total", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("total", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("number", sa.String(length=100), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=True),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("created_by_user_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"]),
        sa.ForeignKeyConstraint(["data_source_id"], ["company_data_sources.id"]),
        sa.ForeignKeyConstraint(["issuer_party_id"], ["parties.id"]),
        sa.ForeignKeyConstraint(["recipient_party_id"], ["parties.id"]),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("company_id", "data_source_id", "idempotency_key", name="uq_invoices_source_idempotency"),
    )
    op.create_index("ix_invoices_company_id", "invoices", ["company_id"])
    op.create_index("ix_invoices_data_source_id", "invoices", ["data_source_id"])
    op.create_index("ix_invoices_created_by_user_id", "invoices", ["created_by_user_id"])

    op.create_table(
        "invoice_lines",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("invoice_id", sa.String(length=36), nullable=False),
        sa.Column("item_id", sa.String(length=36), nullable=True),
        sa.Column("description", sa.String(length=500), nullable=False),
        sa.Column("quantity", sa.Numeric(precision=18, scale=6), nullable=False),
        sa.Column("unit_price", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("tax_ids", sa.JSON(), nullable=False),
        sa.Column("withholding_ids", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["invoice_id"], ["invoices.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["item_id"], ["items.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_invoice_lines_invoice_id", "invoice_lines", ["invoice_id"])

    op.create_table(
        "payments",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("company_id", sa.String(length=36), nullable=False),
        sa.Column("data_source_id", sa.String(length=36), nullable=False),
        sa.Column("payment_date", sa.Date(), nullable=False),
        sa.Column("amount", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("currency_code", sa.String(length=3), nullable=False),
        sa.Column("exchange_rate", sa.Numeric(precision=18, scale=6), nullable=False),
        sa.Column("currency_as_of", sa.Date(), nullable=True),
        sa.Column("invoice_id", sa.String(length=36), nullable=True),
        sa.Column("payment_method", sa.String(length=100), nullable=True),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("created_by_user_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"]),
        sa.ForeignKeyConstraint(["data_source_id"], ["company_data_sources.id"]),
        sa.ForeignKeyConstraint(["invoice_id"], ["invoices.id"]),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("company_id", "data_source_id", "idempotency_key", name="uq_payments_source_idempotency"),
    )
    op.create_index("ix_payments_company_id", "payments", ["company_id"])
    op.create_index("ix_payments_data_source_id", "payments", ["data_source_id"])
    op.create_index("ix_payments_created_by_user_id", "payments", ["created_by_user_id"])

    op.create_table(
        "journal_entries",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("company_id", sa.String(length=36), nullable=False),
        sa.Column("data_source_id", sa.String(length=36), nullable=False),
        sa.Column("entry_date", sa.Date(), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=False),
        sa.Column("source_reference", sa.String(length=255), nullable=True),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("created_by_user_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"]),
        sa.ForeignKeyConstraint(["data_source_id"], ["company_data_sources.id"]),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("company_id", "data_source_id", "idempotency_key", name="uq_journal_entries_source_idempotency"),
    )
    op.create_index("ix_journal_entries_company_id", "journal_entries", ["company_id"])
    op.create_index("ix_journal_entries_data_source_id", "journal_entries", ["data_source_id"])
    op.create_index("ix_journal_entries_created_by_user_id", "journal_entries", ["created_by_user_id"])

    op.create_table(
        "journal_entry_lines",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("journal_entry_id", sa.String(length=36), nullable=False),
        sa.Column("account_code", sa.String(length=100), nullable=False),
        sa.Column("debit", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("credit", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("party_id", sa.String(length=36), nullable=True),
        sa.Column("cost_center", sa.String(length=100), nullable=True),
        sa.ForeignKeyConstraint(["journal_entry_id"], ["journal_entries.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["party_id"], ["parties.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_journal_entry_lines_journal_entry_id", "journal_entry_lines", ["journal_entry_id"])


def downgrade() -> None:
    op.drop_index("ix_journal_entry_lines_journal_entry_id", table_name="journal_entry_lines")
    op.drop_table("journal_entry_lines")
    op.drop_index("ix_journal_entries_created_by_user_id", table_name="journal_entries")
    op.drop_index("ix_journal_entries_data_source_id", table_name="journal_entries")
    op.drop_index("ix_journal_entries_company_id", table_name="journal_entries")
    op.drop_table("journal_entries")
    op.drop_index("ix_payments_created_by_user_id", table_name="payments")
    op.drop_index("ix_payments_data_source_id", table_name="payments")
    op.drop_index("ix_payments_company_id", table_name="payments")
    op.drop_table("payments")
    op.drop_index("ix_invoice_lines_invoice_id", table_name="invoice_lines")
    op.drop_table("invoice_lines")
    op.drop_index("ix_invoices_created_by_user_id", table_name="invoices")
    op.drop_index("ix_invoices_data_source_id", table_name="invoices")
    op.drop_index("ix_invoices_company_id", table_name="invoices")
    op.drop_table("invoices")
    op.drop_index("ix_items_created_by_user_id", table_name="items")
    op.drop_index("ix_items_data_source_id", table_name="items")
    op.drop_index("ix_items_company_id", table_name="items")
    op.drop_table("items")
    op.drop_index("ix_taxes_created_by_user_id", table_name="taxes")
    op.drop_index("ix_taxes_data_source_id", table_name="taxes")
    op.drop_index("ix_taxes_company_id", table_name="taxes")
    op.drop_table("taxes")
