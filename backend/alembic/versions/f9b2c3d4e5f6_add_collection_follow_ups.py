"""add collection follow ups

Revision ID: f9b2c3d4e5f6
Revises: e8a1b2c3d4f5
Create Date: 2026-08-12 15:20:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f9b2c3d4e5f6"
down_revision: Union[str, Sequence[str], None] = "e8a1b2c3d4f5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "collection_follow_ups",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("company_id", sa.String(length=36), nullable=False),
        sa.Column("invoice_id", sa.String(length=36), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("promised_date", sa.Date(), nullable=True),
        sa.Column("note", sa.String(length=280), nullable=True),
        sa.Column("created_by_user_id", sa.Integer(), nullable=False),
        sa.Column("updated_by_user_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "status IN ('pending', 'contacted', 'promise_to_pay', 'resolved', 'cancelled')",
            name="ck_collection_follow_ups_status",
        ),
        sa.CheckConstraint(
            "(status = 'promise_to_pay' AND promised_date IS NOT NULL) OR "
            "(status != 'promise_to_pay' AND promised_date IS NULL)",
            name="ck_collection_follow_ups_promise_date",
        ),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["invoice_id"], ["invoices.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["updated_by_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_collection_follow_ups_company_id", "collection_follow_ups", ["company_id"])
    op.create_index("ix_collection_follow_ups_invoice_id", "collection_follow_ups", ["invoice_id"])
    op.create_index("ix_collection_follow_ups_status", "collection_follow_ups", ["status"])
    op.create_index(
        "ix_collection_follow_ups_created_by_user_id",
        "collection_follow_ups",
        ["created_by_user_id"],
    )
    op.create_index(
        "ix_collection_follow_ups_updated_by_user_id",
        "collection_follow_ups",
        ["updated_by_user_id"],
    )
    op.create_index(
        "ix_collection_follow_ups_company_invoice_updated",
        "collection_follow_ups",
        ["company_id", "invoice_id", "updated_at"],
    )
    op.create_index(
        "ix_collection_follow_ups_company_status_promised",
        "collection_follow_ups",
        ["company_id", "status", "promised_date"],
    )


def downgrade() -> None:
    op.drop_index("ix_collection_follow_ups_company_status_promised", table_name="collection_follow_ups")
    op.drop_index("ix_collection_follow_ups_company_invoice_updated", table_name="collection_follow_ups")
    op.drop_index("ix_collection_follow_ups_updated_by_user_id", table_name="collection_follow_ups")
    op.drop_index("ix_collection_follow_ups_created_by_user_id", table_name="collection_follow_ups")
    op.drop_index("ix_collection_follow_ups_status", table_name="collection_follow_ups")
    op.drop_index("ix_collection_follow_ups_invoice_id", table_name="collection_follow_ups")
    op.drop_index("ix_collection_follow_ups_company_id", table_name="collection_follow_ups")
    op.drop_table("collection_follow_ups")
