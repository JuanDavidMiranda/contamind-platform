"""add bank reconciliation

Revision ID: a1c4e7f9b2d6
Revises: f9b2c3d4e5f6
Create Date: 2026-08-13 11:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a1c4e7f9b2d6"
down_revision: Union[str, Sequence[str], None] = "f9b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "bank_accounts",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("company_id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("bank_name", sa.String(length=100), nullable=True),
        sa.Column("currency_code", sa.String(length=3), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("created_by_user_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("status IN ('active', 'disabled')", name="ck_bank_accounts_status"),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("company_id", "name", name="uq_bank_accounts_company_name"),
    )
    op.create_index("ix_bank_accounts_company_id", "bank_accounts", ["company_id"])
    op.create_index("ix_bank_accounts_status", "bank_accounts", ["status"])
    op.create_index("ix_bank_accounts_created_by_user_id", "bank_accounts", ["created_by_user_id"])
    op.create_index("ix_bank_accounts_company_status", "bank_accounts", ["company_id", "status"])

    op.create_table(
        "bank_statement_imports",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("company_id", sa.String(length=36), nullable=False),
        sa.Column("bank_account_id", sa.String(length=36), nullable=False),
        sa.Column("accepted_rows", sa.Integer(), nullable=False),
        sa.Column("rejected_rows", sa.Integer(), nullable=False),
        sa.Column("duplicate_rows", sa.Integer(), nullable=False),
        sa.Column("created_by_user_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["bank_account_id"], ["bank_accounts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_bank_statement_imports_company_id", "bank_statement_imports", ["company_id"])
    op.create_index("ix_bank_statement_imports_bank_account_id", "bank_statement_imports", ["bank_account_id"])
    op.create_index("ix_bank_statement_imports_created_by_user_id", "bank_statement_imports", ["created_by_user_id"])
    op.create_index("ix_bank_statement_imports_company_created", "bank_statement_imports", ["company_id", "created_at"])

    op.create_table(
        "bank_transactions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("company_id", sa.String(length=36), nullable=False),
        sa.Column("bank_account_id", sa.String(length=36), nullable=False),
        sa.Column("import_id", sa.String(length=36), nullable=False),
        sa.Column("transaction_date", sa.Date(), nullable=False),
        sa.Column("amount", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("currency_code", sa.String(length=3), nullable=False),
        sa.Column("description", sa.String(length=280), nullable=True),
        sa.Column("reference", sa.String(length=100), nullable=True),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("match_candidate_count", sa.Integer(), nullable=False),
        sa.Column("suggested_payment_id", sa.String(length=36), nullable=True),
        sa.Column("matched_payment_id", sa.String(length=36), nullable=True),
        sa.Column("created_by_user_id", sa.Integer(), nullable=False),
        sa.Column("reviewed_by_user_id", sa.Integer(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("amount != 0", name="ck_bank_transactions_non_zero_amount"),
        sa.CheckConstraint("match_candidate_count >= 0", name="ck_bank_transactions_candidates"),
        sa.CheckConstraint(
            "status IN ('pending', 'suggested', 'reconciled', 'dismissed', 'excluded')",
            name="ck_bank_transactions_status",
        ),
        sa.ForeignKeyConstraint(["bank_account_id"], ["bank_accounts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["import_id"], ["bank_statement_imports.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["matched_payment_id"], ["payments.id"]),
        sa.ForeignKeyConstraint(["reviewed_by_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["suggested_payment_id"], ["payments.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("bank_account_id", "fingerprint", name="uq_bank_transactions_account_fingerprint"),
        sa.UniqueConstraint("matched_payment_id", name="uq_bank_transactions_matched_payment"),
    )
    for column in (
        "company_id",
        "bank_account_id",
        "import_id",
        "status",
        "suggested_payment_id",
        "matched_payment_id",
        "created_by_user_id",
        "reviewed_by_user_id",
    ):
        op.create_index(f"ix_bank_transactions_{column}", "bank_transactions", [column])
    op.create_index("ix_bank_transactions_company_status", "bank_transactions", ["company_id", "status"])
    op.create_index("ix_bank_transactions_account_date", "bank_transactions", ["bank_account_id", "transaction_date"])


def downgrade() -> None:
    op.drop_table("bank_transactions")
    op.drop_table("bank_statement_imports")
    op.drop_table("bank_accounts")
