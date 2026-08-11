"""add provider sync job queue

Revision ID: c3e7a9f2d6b1
Revises: a9d4e1c2b7f0
Create Date: 2026-08-11 10:30:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c3e7a9f2d6b1"
down_revision: Union[str, Sequence[str], None] = "a9d4e1c2b7f0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "provider_sync_jobs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("data_source_id", sa.String(length=36), nullable=False),
        sa.Column("active_data_source_id", sa.String(length=36), nullable=True),
        sa.Column("company_id", sa.String(length=36), nullable=False),
        sa.Column("provider_id", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("page_size", sa.Integer(), nullable=False),
        sa.Column("cursor", sa.String(length=512), nullable=True),
        sa.Column("processed_records", sa.Integer(), nullable=False),
        sa.Column("pages_processed", sa.Integer(), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("available_at", sa.DateTime(), nullable=False),
        sa.Column("lease_expires_at", sa.DateTime(), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("correlation_id", sa.String(length=64), nullable=True),
        sa.Column("created_by_user_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"]),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(
            ["data_source_id"], ["company_data_sources.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("active_data_source_id", name="uq_provider_sync_jobs_active_source"),
    )
    op.create_index("ix_provider_sync_jobs_data_source_id", "provider_sync_jobs", ["data_source_id"])
    op.create_index("ix_provider_sync_jobs_company_id", "provider_sync_jobs", ["company_id"])
    op.create_index("ix_provider_sync_jobs_provider_id", "provider_sync_jobs", ["provider_id"])
    op.create_index("ix_provider_sync_jobs_status", "provider_sync_jobs", ["status"])
    op.create_index("ix_provider_sync_jobs_available_at", "provider_sync_jobs", ["available_at"])
    op.create_index(
        "ix_provider_sync_jobs_lease_expires_at", "provider_sync_jobs", ["lease_expires_at"]
    )
    op.create_index(
        "ix_provider_sync_jobs_created_by_user_id",
        "provider_sync_jobs",
        ["created_by_user_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_provider_sync_jobs_created_by_user_id", table_name="provider_sync_jobs")
    op.drop_index("ix_provider_sync_jobs_lease_expires_at", table_name="provider_sync_jobs")
    op.drop_index("ix_provider_sync_jobs_available_at", table_name="provider_sync_jobs")
    op.drop_index("ix_provider_sync_jobs_status", table_name="provider_sync_jobs")
    op.drop_index("ix_provider_sync_jobs_provider_id", table_name="provider_sync_jobs")
    op.drop_index("ix_provider_sync_jobs_company_id", table_name="provider_sync_jobs")
    op.drop_index("ix_provider_sync_jobs_data_source_id", table_name="provider_sync_jobs")
    op.drop_table("provider_sync_jobs")
