"""add electronic invoice evidence

Revision ID: b3d5e7f9a1c2
Revises: a1c4e7f9b2d6
Create Date: 2026-08-18 09:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b3d5e7f9a1c2"
down_revision: Union[str, Sequence[str], None] = "a1c4e7f9b2d6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("invoices", sa.Column("electronic_status", sa.String(length=50), nullable=True))
    op.add_column("invoices", sa.Column("electronic_reference", sa.String(length=255), nullable=True))
    op.add_column("invoices", sa.Column("electronic_status_at", sa.DateTime(), nullable=True))
    op.create_index(
        "ix_invoices_company_electronic_status",
        "invoices",
        ["company_id", "electronic_status"],
    )


def downgrade() -> None:
    op.drop_index("ix_invoices_company_electronic_status", table_name="invoices")
    op.drop_column("invoices", "electronic_status_at")
    op.drop_column("invoices", "electronic_reference")
    op.drop_column("invoices", "electronic_status")
