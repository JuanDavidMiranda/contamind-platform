"""add verified bank balance snapshots

Revision ID: a2c4e6f8b0d1
Revises: c7e1f4a8b2d3
Create Date: 2026-08-14 10:10:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a2c4e6f8b0d1"
down_revision: Union[str, Sequence[str], None] = "c7e1f4a8b2d3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "bank_balance_snapshots",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("company_id", sa.String(length=36), nullable=False),
        sa.Column("bank_account_id", sa.String(length=36), nullable=False),
        sa.Column("as_of_date", sa.Date(), nullable=False),
        sa.Column("balance", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("currency_code", sa.String(length=3), nullable=False),
        sa.Column("verified_by_user_id", sa.Integer(), nullable=False),
        sa.Column("verified_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["bank_account_id"], ["bank_accounts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["verified_by_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("bank_account_id", "as_of_date", name="uq_bank_balance_snapshots_account_date"),
    )
    op.create_index(
        "ix_bank_balance_snapshots_company_date",
        "bank_balance_snapshots",
        ["company_id", "as_of_date"],
    )
    op.create_index(
        "ix_bank_balance_snapshots_company_id",
        "bank_balance_snapshots",
        ["company_id"],
    )
    op.create_index(
        "ix_bank_balance_snapshots_bank_account_id",
        "bank_balance_snapshots",
        ["bank_account_id"],
    )
    op.create_index(
        "ix_bank_balance_snapshots_verified_by_user_id",
        "bank_balance_snapshots",
        ["verified_by_user_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_bank_balance_snapshots_verified_by_user_id", table_name="bank_balance_snapshots")
    op.drop_index("ix_bank_balance_snapshots_bank_account_id", table_name="bank_balance_snapshots")
    op.drop_index("ix_bank_balance_snapshots_company_id", table_name="bank_balance_snapshots")
    op.drop_index("ix_bank_balance_snapshots_company_date", table_name="bank_balance_snapshots")
    op.drop_table("bank_balance_snapshots")
