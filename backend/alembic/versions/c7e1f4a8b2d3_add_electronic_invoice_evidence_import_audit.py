"""add electronic invoice evidence import audit

Revision ID: c7e1f4a8b2d3
Revises: b3d5e7f9a1c2
Create Date: 2026-08-18 11:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c7e1f4a8b2d3"
down_revision: Union[str, Sequence[str], None] = "b3d5e7f9a1c2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "electronic_invoice_evidence_imports",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("company_id", sa.String(length=36), nullable=False),
        sa.Column("file_format", sa.String(length=10), nullable=False),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column("accepted_rows", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("duplicate_rows", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("rejected_rows", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_by_user_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "file_format IN ('csv', 'xlsx')",
            name="ck_electronic_invoice_evidence_imports_file_format",
        ),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"]),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_electronic_invoice_evidence_imports_company_created",
        "electronic_invoice_evidence_imports",
        ["company_id", "created_at"],
    )
    op.create_index(
        "ix_electronic_invoice_evidence_imports_company_id",
        "electronic_invoice_evidence_imports",
        ["company_id"],
    )
    op.create_index(
        "ix_electronic_invoice_evidence_imports_created_by_user_id",
        "electronic_invoice_evidence_imports",
        ["created_by_user_id"],
    )
    op.create_table(
        "electronic_invoice_evidence_import_rows",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("import_id", sa.String(length=36), nullable=False),
        sa.Column("company_id", sa.String(length=36), nullable=False),
        sa.Column("invoice_id", sa.String(length=36), nullable=True),
        sa.Column("row_number", sa.Integer(), nullable=False),
        sa.Column("outcome", sa.String(length=20), nullable=False),
        sa.Column("reason", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "outcome IN ('accepted', 'duplicate', 'rejected')",
            name="ck_electronic_invoice_evidence_import_rows_outcome",
        ),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"]),
        sa.ForeignKeyConstraint(["import_id"], ["electronic_invoice_evidence_imports.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["invoice_id"], ["invoices.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_electronic_invoice_evidence_import_rows_company_id",
        "electronic_invoice_evidence_import_rows",
        ["company_id"],
    )
    op.create_index(
        "ix_electronic_invoice_evidence_import_rows_import_id",
        "electronic_invoice_evidence_import_rows",
        ["import_id"],
    )
    op.create_index(
        "ix_electronic_invoice_evidence_import_rows_import_outcome",
        "electronic_invoice_evidence_import_rows",
        ["import_id", "outcome"],
    )
    op.create_index(
        "ix_electronic_invoice_evidence_import_rows_invoice_id",
        "electronic_invoice_evidence_import_rows",
        ["invoice_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_electronic_invoice_evidence_import_rows_invoice_id",
        table_name="electronic_invoice_evidence_import_rows",
    )
    op.drop_index(
        "ix_electronic_invoice_evidence_import_rows_import_outcome",
        table_name="electronic_invoice_evidence_import_rows",
    )
    op.drop_index(
        "ix_electronic_invoice_evidence_import_rows_import_id",
        table_name="electronic_invoice_evidence_import_rows",
    )
    op.drop_index(
        "ix_electronic_invoice_evidence_import_rows_company_id",
        table_name="electronic_invoice_evidence_import_rows",
    )
    op.drop_table("electronic_invoice_evidence_import_rows")
    op.drop_index(
        "ix_electronic_invoice_evidence_imports_created_by_user_id",
        table_name="electronic_invoice_evidence_imports",
    )
    op.drop_index(
        "ix_electronic_invoice_evidence_imports_company_id",
        table_name="electronic_invoice_evidence_imports",
    )
    op.drop_index(
        "ix_electronic_invoice_evidence_imports_company_created",
        table_name="electronic_invoice_evidence_imports",
    )
    op.drop_table("electronic_invoice_evidence_imports")
