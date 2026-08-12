"""add invoice payment terms

Revision ID: e8a1b2c3d4f5
Revises: d6f2a9c8b4e1
Create Date: 2026-08-12 15:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e8a1b2c3d4f5"
down_revision: Union[str, Sequence[str], None] = "d6f2a9c8b4e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("invoices", sa.Column("due_date", sa.Date(), nullable=True))
    op.add_column("invoices", sa.Column("payment_terms_days", sa.Integer(), nullable=True))
    op.add_column("invoices", sa.Column("updated_by_user_id", sa.Integer(), nullable=True))
    op.add_column(
        "invoices",
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_check_constraint(
        "ck_invoices_due_date_on_or_after_issue",
        "invoices",
        "due_date IS NULL OR due_date >= issue_date",
    )
    op.create_check_constraint(
        "ck_invoices_payment_terms_days_range",
        "invoices",
        "payment_terms_days IS NULL OR payment_terms_days BETWEEN 0 AND 3650",
    )
    op.create_foreign_key(
        "fk_invoices_updated_by_user_id_users",
        "invoices",
        "users",
        ["updated_by_user_id"],
        ["id"],
    )
    op.create_index("ix_invoices_updated_by_user_id", "invoices", ["updated_by_user_id"])
    op.create_index(
        "ix_invoices_company_type_due_date",
        "invoices",
        ["company_id", "invoice_type", "due_date"],
    )


def downgrade() -> None:
    op.drop_index("ix_invoices_company_type_due_date", table_name="invoices")
    op.drop_index("ix_invoices_updated_by_user_id", table_name="invoices")
    op.drop_constraint("fk_invoices_updated_by_user_id_users", "invoices", type_="foreignkey")
    op.drop_constraint("ck_invoices_payment_terms_days_range", "invoices", type_="check")
    op.drop_constraint("ck_invoices_due_date_on_or_after_issue", "invoices", type_="check")
    op.drop_column("invoices", "updated_at")
    op.drop_column("invoices", "updated_by_user_id")
    op.drop_column("invoices", "payment_terms_days")
    op.drop_column("invoices", "due_date")
