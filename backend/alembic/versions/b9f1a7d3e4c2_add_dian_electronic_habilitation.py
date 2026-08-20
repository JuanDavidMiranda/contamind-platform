"""add DIAN electronic invoicing habilitation core

Revision ID: b9f1a7d3e4c2
Revises: a7b4c9d2e6f1
Create Date: 2026-08-20 16:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "b9f1a7d3e4c2"
down_revision: Union[str, Sequence[str], None] = "a7b4c9d2e6f1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "dian_fiscal_profiles",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("company_id", sa.String(length=36), nullable=False),
        sa.Column("data_source_id", sa.String(length=36), nullable=True),
        sa.Column("environment", sa.String(length=20), nullable=False, server_default="habilitation"),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="draft"),
        sa.Column("software_test_set_id", sa.String(length=128), nullable=True),
        sa.Column("signature_policy_identifier", sa.String(length=2048), nullable=True),
        sa.Column("signature_policy_digest_base64", sa.String(length=128), nullable=True),
        sa.Column("signature_policy_qualifier_url", sa.String(length=2048), nullable=True),
        sa.Column("legal_name", sa.String(length=255), nullable=False),
        sa.Column("nit", sa.String(length=30), nullable=False),
        sa.Column("check_digit", sa.String(length=1), nullable=False),
        sa.Column("document_type", sa.String(length=2), nullable=False, server_default="31"),
        sa.Column("tax_regime", sa.String(length=100), nullable=True),
        sa.Column("tax_responsibilities", sa.JSON(), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("phone", sa.String(length=50), nullable=True),
        sa.Column("address", sa.String(length=255), nullable=False),
        sa.Column("city_code", sa.String(length=10), nullable=False),
        sa.Column("city_name", sa.String(length=100), nullable=False),
        sa.Column("department_code", sa.String(length=10), nullable=False),
        sa.Column("department_name", sa.String(length=100), nullable=False),
        sa.Column("country_code", sa.String(length=2), nullable=False, server_default="CO"),
        sa.Column("created_by_user_id", sa.Integer(), nullable=False),
        sa.Column("updated_by_user_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "environment = 'habilitation'", name="ck_dian_fiscal_profiles_habilitation_only"
        ),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["data_source_id"], ["company_data_sources.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["updated_by_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("company_id", name="uq_dian_fiscal_profiles_company"),
        sa.UniqueConstraint("data_source_id", name="uq_dian_fiscal_profiles_source"),
    )
    op.create_index("ix_dian_fiscal_profiles_tenant_id", "dian_fiscal_profiles", ["tenant_id"])
    op.create_index("ix_dian_fiscal_profiles_company_id", "dian_fiscal_profiles", ["company_id"])
    op.create_index("ix_dian_fiscal_profiles_data_source_id", "dian_fiscal_profiles", ["data_source_id"])
    op.create_index("ix_dian_fiscal_profiles_status", "dian_fiscal_profiles", ["status"])
    op.create_index("ix_dian_fiscal_profiles_nit", "dian_fiscal_profiles", ["nit"])
    op.create_index(
        "ix_dian_fiscal_profiles_created_by_user_id",
        "dian_fiscal_profiles",
        ["created_by_user_id"],
    )
    op.create_index(
        "ix_dian_fiscal_profiles_updated_by_user_id",
        "dian_fiscal_profiles",
        ["updated_by_user_id"],
    )

    op.create_table(
        "dian_numbering_ranges",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("profile_id", sa.String(length=36), nullable=False),
        sa.Column("company_id", sa.String(length=36), nullable=False),
        sa.Column("prefix", sa.String(length=20), nullable=False),
        sa.Column("resolution_number", sa.String(length=100), nullable=False),
        sa.Column("resolution_date", sa.Date(), nullable=False),
        sa.Column("valid_from", sa.Date(), nullable=False),
        sa.Column("valid_to", sa.Date(), nullable=False),
        sa.Column("range_from", sa.Integer(), nullable=False),
        sa.Column("range_to", sa.Integer(), nullable=False),
        sa.Column("next_number", sa.Integer(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_by_user_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("range_from > 0", name="ck_dian_numbering_ranges_from_positive"),
        sa.CheckConstraint("range_to >= range_from", name="ck_dian_numbering_ranges_bounds"),
        sa.CheckConstraint(
            "next_number >= range_from AND next_number <= range_to + 1",
            name="ck_dian_numbering_ranges_next_bounds",
        ),
        sa.ForeignKeyConstraint(["profile_id"], ["dian_fiscal_profiles.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "profile_id",
            "prefix",
            "range_from",
            "range_to",
            name="uq_dian_numbering_ranges_profile_prefix_bounds",
        ),
    )
    op.create_index("ix_dian_numbering_ranges_profile_id", "dian_numbering_ranges", ["profile_id"])
    op.create_index("ix_dian_numbering_ranges_company_id", "dian_numbering_ranges", ["company_id"])
    op.create_index("ix_dian_numbering_ranges_prefix", "dian_numbering_ranges", ["prefix"])
    op.create_index("ix_dian_numbering_ranges_active", "dian_numbering_ranges", ["active"])
    op.create_index(
        "ix_dian_numbering_ranges_created_by_user_id",
        "dian_numbering_ranges",
        ["created_by_user_id"],
    )

    op.create_table(
        "dian_electronic_documents",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("profile_id", sa.String(length=36), nullable=False),
        sa.Column("company_id", sa.String(length=36), nullable=False),
        sa.Column("source_invoice_id", sa.String(length=36), nullable=True),
        sa.Column("corrects_document_id", sa.String(length=36), nullable=True),
        sa.Column("document_type", sa.String(length=30), nullable=False, server_default="invoice"),
        sa.Column("prefix", sa.String(length=20), nullable=False),
        sa.Column("consecutive", sa.Integer(), nullable=False),
        sa.Column("document_number", sa.String(length=50), nullable=False),
        sa.Column("issue_date", sa.Date(), nullable=False),
        sa.Column("currency_code", sa.String(length=3), nullable=False),
        sa.Column("payable_amount", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="prepared"),
        sa.Column("source_snapshot_sha256", sa.String(length=64), nullable=False),
        sa.Column("unsigned_xml_sha256", sa.String(length=64), nullable=True),
        sa.Column("signed_xml_sha256", sa.String(length=64), nullable=False),
        sa.Column("signed_xml_ciphertext", sa.Text(), nullable=False),
        sa.Column("signed_zip_ciphertext", sa.Text(), nullable=False),
        sa.Column("artifact_key_version", sa.String(length=32), nullable=False),
        sa.Column("dian_document_key", sa.String(length=128), nullable=True),
        sa.Column("created_by_user_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "consecutive > 0", name="ck_dian_electronic_documents_consecutive_positive"
        ),
        sa.ForeignKeyConstraint(["profile_id"], ["dian_fiscal_profiles.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_invoice_id"], ["invoices.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["corrects_document_id"], ["dian_electronic_documents.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source_invoice_id", name="uq_dian_electronic_documents_invoice"),
        sa.UniqueConstraint("corrects_document_id", name="uq_dian_electronic_documents_correction"),
    )
    op.create_index("ix_dian_electronic_documents_profile_id", "dian_electronic_documents", ["profile_id"])
    op.create_index("ix_dian_electronic_documents_company_id", "dian_electronic_documents", ["company_id"])
    op.create_index("ix_dian_electronic_documents_source_invoice_id", "dian_electronic_documents", ["source_invoice_id"])
    op.create_index(
        "ix_dian_electronic_documents_corrects_document_id",
        "dian_electronic_documents",
        ["corrects_document_id"],
    )
    op.create_index("ix_dian_electronic_documents_document_number", "dian_electronic_documents", ["document_number"])
    op.create_index("ix_dian_electronic_documents_status", "dian_electronic_documents", ["status"])
    op.create_index(
        "ix_dian_electronic_documents_created_by_user_id",
        "dian_electronic_documents",
        ["created_by_user_id"],
    )
    op.create_index(
        "ix_dian_electronic_documents_company_status",
        "dian_electronic_documents",
        ["company_id", "status"],
    )
    op.create_index(
        "uq_dian_electronic_documents_unrejected_number",
        "dian_electronic_documents",
        ["company_id", "prefix", "consecutive"],
        unique=True,
        sqlite_where=sa.text("status <> 'rejected'"),
        postgresql_where=sa.text("status <> 'rejected'"),
    )

    op.create_table(
        "dian_electronic_outbox_jobs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("document_id", sa.String(length=36), nullable=False),
        sa.Column("active_document_id", sa.String(length=36), nullable=True),
        sa.Column("company_id", sa.String(length=36), nullable=False),
        sa.Column("operation", sa.String(length=30), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("available_at", sa.DateTime(), nullable=False),
        sa.Column("lease_expires_at", sa.DateTime(), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("correlation_id", sa.String(length=64), nullable=True),
        sa.Column("created_by_user_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["document_id"], ["dian_electronic_documents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("active_document_id", name="uq_dian_electronic_outbox_active_document"),
    )
    op.create_index("ix_dian_electronic_outbox_jobs_document_id", "dian_electronic_outbox_jobs", ["document_id"])
    op.create_index("ix_dian_electronic_outbox_jobs_company_id", "dian_electronic_outbox_jobs", ["company_id"])
    op.create_index("ix_dian_electronic_outbox_jobs_status", "dian_electronic_outbox_jobs", ["status"])
    op.create_index("ix_dian_electronic_outbox_jobs_available_at", "dian_electronic_outbox_jobs", ["available_at"])
    op.create_index("ix_dian_electronic_outbox_jobs_lease_expires_at", "dian_electronic_outbox_jobs", ["lease_expires_at"])
    op.create_index(
        "ix_dian_electronic_outbox_jobs_created_by_user_id",
        "dian_electronic_outbox_jobs",
        ["created_by_user_id"],
    )
    op.create_index(
        "ix_dian_electronic_outbox_ready",
        "dian_electronic_outbox_jobs",
        ["status", "available_at"],
    )

    op.create_table(
        "dian_electronic_submissions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("document_id", sa.String(length=36), nullable=False),
        sa.Column("job_id", sa.String(length=36), nullable=True),
        sa.Column("company_id", sa.String(length=36), nullable=False),
        sa.Column("operation", sa.String(length=30), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("request_sha256", sa.String(length=64), nullable=False),
        sa.Column("track_id", sa.String(length=255), nullable=True),
        sa.Column("status_code", sa.String(length=100), nullable=True),
        sa.Column("status_description", sa.String(length=1000), nullable=True),
        sa.Column("status_message", sa.String(length=1000), nullable=True),
        sa.Column("error_message", sa.String(length=1000), nullable=True),
        sa.Column("is_valid", sa.Boolean(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["document_id"], ["dian_electronic_documents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["job_id"], ["dian_electronic_outbox_jobs.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_dian_electronic_submissions_document_id", "dian_electronic_submissions", ["document_id"])
    op.create_index("ix_dian_electronic_submissions_job_id", "dian_electronic_submissions", ["job_id"])
    op.create_index("ix_dian_electronic_submissions_company_id", "dian_electronic_submissions", ["company_id"])
    op.create_index("ix_dian_electronic_submissions_status", "dian_electronic_submissions", ["status"])
    op.create_index("ix_dian_electronic_submissions_track_id", "dian_electronic_submissions", ["track_id"])
    op.create_index(
        "ix_dian_electronic_submissions_document_created",
        "dian_electronic_submissions",
        ["document_id", "created_at"],
    )

    op.create_table(
        "dian_electronic_document_status_events",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("document_id", sa.String(length=36), nullable=False),
        sa.Column("company_id", sa.String(length=36), nullable=False),
        sa.Column("previous_status", sa.String(length=30), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=True),
        sa.Column("message", sa.String(length=500), nullable=True),
        sa.Column("actor_user_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["document_id"], ["dian_electronic_documents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_dian_electronic_document_status_events_document_id",
        "dian_electronic_document_status_events",
        ["document_id"],
    )
    op.create_index(
        "ix_dian_electronic_document_status_events_company_id",
        "dian_electronic_document_status_events",
        ["company_id"],
    )
    op.create_index(
        "ix_dian_electronic_document_status_events_status",
        "dian_electronic_document_status_events",
        ["status"],
    )
    op.create_index(
        "ix_dian_electronic_document_status_events_actor_user_id",
        "dian_electronic_document_status_events",
        ["actor_user_id"],
    )
    op.create_index(
        "ix_dian_electronic_status_events_document_created",
        "dian_electronic_document_status_events",
        ["document_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_dian_electronic_status_events_document_created",
        table_name="dian_electronic_document_status_events",
    )
    op.drop_index(
        "ix_dian_electronic_document_status_events_actor_user_id",
        table_name="dian_electronic_document_status_events",
    )
    op.drop_index(
        "ix_dian_electronic_document_status_events_status",
        table_name="dian_electronic_document_status_events",
    )
    op.drop_index(
        "ix_dian_electronic_document_status_events_company_id",
        table_name="dian_electronic_document_status_events",
    )
    op.drop_index(
        "ix_dian_electronic_document_status_events_document_id",
        table_name="dian_electronic_document_status_events",
    )
    op.drop_table("dian_electronic_document_status_events")
    op.drop_index(
        "ix_dian_electronic_submissions_document_created",
        table_name="dian_electronic_submissions",
    )
    op.drop_index("ix_dian_electronic_submissions_track_id", table_name="dian_electronic_submissions")
    op.drop_index("ix_dian_electronic_submissions_status", table_name="dian_electronic_submissions")
    op.drop_index("ix_dian_electronic_submissions_company_id", table_name="dian_electronic_submissions")
    op.drop_index("ix_dian_electronic_submissions_job_id", table_name="dian_electronic_submissions")
    op.drop_index("ix_dian_electronic_submissions_document_id", table_name="dian_electronic_submissions")
    op.drop_table("dian_electronic_submissions")
    op.drop_index("ix_dian_electronic_outbox_ready", table_name="dian_electronic_outbox_jobs")
    op.drop_index(
        "ix_dian_electronic_outbox_jobs_created_by_user_id",
        table_name="dian_electronic_outbox_jobs",
    )
    op.drop_index(
        "ix_dian_electronic_outbox_jobs_lease_expires_at",
        table_name="dian_electronic_outbox_jobs",
    )
    op.drop_index("ix_dian_electronic_outbox_jobs_available_at", table_name="dian_electronic_outbox_jobs")
    op.drop_index("ix_dian_electronic_outbox_jobs_status", table_name="dian_electronic_outbox_jobs")
    op.drop_index("ix_dian_electronic_outbox_jobs_company_id", table_name="dian_electronic_outbox_jobs")
    op.drop_index("ix_dian_electronic_outbox_jobs_document_id", table_name="dian_electronic_outbox_jobs")
    op.drop_table("dian_electronic_outbox_jobs")
    op.drop_index(
        "ix_dian_electronic_documents_company_status",
        table_name="dian_electronic_documents",
    )
    op.drop_index(
        "uq_dian_electronic_documents_unrejected_number",
        table_name="dian_electronic_documents",
    )
    op.drop_index(
        "ix_dian_electronic_documents_created_by_user_id",
        table_name="dian_electronic_documents",
    )
    op.drop_index("ix_dian_electronic_documents_status", table_name="dian_electronic_documents")
    op.drop_index(
        "ix_dian_electronic_documents_document_number",
        table_name="dian_electronic_documents",
    )
    op.drop_index(
        "ix_dian_electronic_documents_source_invoice_id",
        table_name="dian_electronic_documents",
    )
    op.drop_index(
        "ix_dian_electronic_documents_corrects_document_id",
        table_name="dian_electronic_documents",
    )
    op.drop_index("ix_dian_electronic_documents_company_id", table_name="dian_electronic_documents")
    op.drop_index("ix_dian_electronic_documents_profile_id", table_name="dian_electronic_documents")
    op.drop_table("dian_electronic_documents")
    op.drop_index(
        "ix_dian_numbering_ranges_created_by_user_id",
        table_name="dian_numbering_ranges",
    )
    op.drop_index("ix_dian_numbering_ranges_active", table_name="dian_numbering_ranges")
    op.drop_index("ix_dian_numbering_ranges_prefix", table_name="dian_numbering_ranges")
    op.drop_index("ix_dian_numbering_ranges_company_id", table_name="dian_numbering_ranges")
    op.drop_index("ix_dian_numbering_ranges_profile_id", table_name="dian_numbering_ranges")
    op.drop_table("dian_numbering_ranges")
    op.drop_index(
        "ix_dian_fiscal_profiles_updated_by_user_id", table_name="dian_fiscal_profiles"
    )
    op.drop_index(
        "ix_dian_fiscal_profiles_created_by_user_id", table_name="dian_fiscal_profiles"
    )
    op.drop_index("ix_dian_fiscal_profiles_nit", table_name="dian_fiscal_profiles")
    op.drop_index("ix_dian_fiscal_profiles_status", table_name="dian_fiscal_profiles")
    op.drop_index("ix_dian_fiscal_profiles_data_source_id", table_name="dian_fiscal_profiles")
    op.drop_index("ix_dian_fiscal_profiles_company_id", table_name="dian_fiscal_profiles")
    op.drop_index("ix_dian_fiscal_profiles_tenant_id", table_name="dian_fiscal_profiles")
    op.drop_table("dian_fiscal_profiles")
