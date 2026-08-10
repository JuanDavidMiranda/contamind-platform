"""add provider connection lifecycle

Revision ID: a9d4e1c2b7f0
Revises: f2b6d8c4a1e9
Create Date: 2026-08-10 17:20:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a9d4e1c2b7f0"
down_revision: Union[str, Sequence[str], None] = "f2b6d8c4a1e9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "company_data_sources",
        sa.Column("last_connection_checked_at", sa.DateTime(), nullable=True),
    )
    op.add_column(
        "company_data_sources",
        sa.Column("last_sync_cursor", sa.String(length=512), nullable=True),
    )
    op.create_table(
        "provider_credentials",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("data_source_id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("company_id", sa.String(length=36), nullable=False),
        sa.Column("provider_id", sa.String(length=64), nullable=False),
        sa.Column("ciphertext", sa.Text(), nullable=False),
        sa.Column("key_version", sa.String(length=32), nullable=False),
        sa.Column("created_by_user_id", sa.Integer(), nullable=True),
        sa.Column("updated_by_user_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"]),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["data_source_id"], ["company_data_sources.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.ForeignKeyConstraint(["updated_by_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("data_source_id", name="uq_provider_credentials_data_source"),
    )
    op.create_index("ix_provider_credentials_data_source_id", "provider_credentials", ["data_source_id"])
    op.create_index("ix_provider_credentials_tenant_id", "provider_credentials", ["tenant_id"])
    op.create_index("ix_provider_credentials_company_id", "provider_credentials", ["company_id"])
    op.create_index("ix_provider_credentials_provider_id", "provider_credentials", ["provider_id"])
    op.create_index(
        "ix_provider_credentials_created_by_user_id", "provider_credentials", ["created_by_user_id"]
    )
    op.create_index(
        "ix_provider_credentials_updated_by_user_id", "provider_credentials", ["updated_by_user_id"]
    )

    op.create_table(
        "provider_sync_runs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("data_source_id", sa.String(length=36), nullable=False),
        sa.Column("company_id", sa.String(length=36), nullable=False),
        sa.Column("provider_id", sa.String(length=64), nullable=False),
        sa.Column("operation", sa.String(length=50), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("cursor_before", sa.String(length=512), nullable=True),
        sa.Column("cursor_after", sa.String(length=512), nullable=True),
        sa.Column("processed_records", sa.Integer(), nullable=False),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("correlation_id", sa.String(length=64), nullable=True),
        sa.Column("created_by_user_id", sa.Integer(), nullable=True),
        sa.Column("started_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"]),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["data_source_id"], ["company_data_sources.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_provider_sync_runs_data_source_id", "provider_sync_runs", ["data_source_id"])
    op.create_index("ix_provider_sync_runs_company_id", "provider_sync_runs", ["company_id"])
    op.create_index("ix_provider_sync_runs_provider_id", "provider_sync_runs", ["provider_id"])
    op.create_index("ix_provider_sync_runs_status", "provider_sync_runs", ["status"])
    op.create_index(
        "ix_provider_sync_runs_created_by_user_id", "provider_sync_runs", ["created_by_user_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_provider_sync_runs_created_by_user_id", table_name="provider_sync_runs")
    op.drop_index("ix_provider_sync_runs_status", table_name="provider_sync_runs")
    op.drop_index("ix_provider_sync_runs_provider_id", table_name="provider_sync_runs")
    op.drop_index("ix_provider_sync_runs_company_id", table_name="provider_sync_runs")
    op.drop_index("ix_provider_sync_runs_data_source_id", table_name="provider_sync_runs")
    op.drop_table("provider_sync_runs")
    op.drop_index("ix_provider_credentials_updated_by_user_id", table_name="provider_credentials")
    op.drop_index("ix_provider_credentials_created_by_user_id", table_name="provider_credentials")
    op.drop_index("ix_provider_credentials_provider_id", table_name="provider_credentials")
    op.drop_index("ix_provider_credentials_company_id", table_name="provider_credentials")
    op.drop_index("ix_provider_credentials_tenant_id", table_name="provider_credentials")
    op.drop_index("ix_provider_credentials_data_source_id", table_name="provider_credentials")
    op.drop_table("provider_credentials")
    op.drop_column("company_data_sources", "last_sync_cursor")
    op.drop_column("company_data_sources", "last_connection_checked_at")
