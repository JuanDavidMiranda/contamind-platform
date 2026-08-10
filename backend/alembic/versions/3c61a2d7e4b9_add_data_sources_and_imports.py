"""add data sources and imports

Revision ID: 3c61a2d7e4b9
Revises: 87ff91bf578e
Create Date: 2026-08-10 10:30:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "3c61a2d7e4b9"
down_revision: Union[str, Sequence[str], None] = "87ff91bf578e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "company_data_sources",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("company_id", sa.String(length=36), nullable=False),
        sa.Column("connector_id", sa.String(length=64), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("kind", sa.String(length=50), nullable=False),
        sa.Column("mode", sa.String(length=50), nullable=False),
        sa.Column("capabilities", sa.JSON(), nullable=False),
        sa.Column("provider_id", sa.String(length=64), nullable=True),
        sa.Column("credential_reference", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("last_synced_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_company_data_sources_tenant_id", "company_data_sources", ["tenant_id"])
    op.create_index("ix_company_data_sources_company_id", "company_data_sources", ["company_id"])
    op.create_index("ix_company_data_sources_connector_id", "company_data_sources", ["connector_id"])
    op.create_index("ix_company_data_sources_status", "company_data_sources", ["status"])

    op.create_table(
        "import_profiles",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("data_source_id", sa.String(length=36), nullable=False),
        sa.Column("entity", sa.String(length=50), nullable=False),
        sa.Column("file_format", sa.String(length=20), nullable=False),
        sa.Column("column_mapping", sa.JSON(), nullable=False),
        sa.Column("default_party_type", sa.String(length=20), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_import_profiles_data_source_id", "import_profiles", ["data_source_id"])

    op.create_table(
        "import_batches",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("data_source_id", sa.String(length=36), nullable=False),
        sa.Column("company_id", sa.String(length=36), nullable=False),
        sa.Column("entity", sa.String(length=50), nullable=False),
        sa.Column("file_format", sa.String(length=20), nullable=False),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column("accepted_rows", sa.Integer(), nullable=False),
        sa.Column("rejected_rows", sa.Integer(), nullable=False),
        sa.Column("correlation_id", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_import_batches_data_source_id", "import_batches", ["data_source_id"])
    op.create_index("ix_import_batches_company_id", "import_batches", ["company_id"])

    op.create_table(
        "parties",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("company_id", sa.String(length=36), nullable=False),
        sa.Column("data_source_id", sa.String(length=36), nullable=True),
        sa.Column("party_type", sa.String(length=20), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("document_type", sa.String(length=10), nullable=True),
        sa.Column("document_number", sa.String(length=50), nullable=True),
        sa.Column("email", sa.String(length=255), nullable=True),
        sa.Column("phone", sa.String(length=50), nullable=True),
        sa.Column("city", sa.String(length=100), nullable=True),
        sa.Column("address", sa.String(length=255), nullable=True),
        sa.Column("fiscal_responsibility", sa.String(length=100), nullable=True),
        sa.Column("external_id", sa.String(length=255), nullable=True),
        sa.Column("integration_id", sa.String(length=512), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_parties_company_id", "parties", ["company_id"])
    op.create_index("ix_parties_data_source_id", "parties", ["data_source_id"])
    op.create_index("ix_parties_document_number", "parties", ["document_number"])
    op.create_index("ix_parties_external_id", "parties", ["external_id"])


def downgrade() -> None:
    op.drop_index("ix_parties_external_id", table_name="parties")
    op.drop_index("ix_parties_document_number", table_name="parties")
    op.drop_index("ix_parties_data_source_id", table_name="parties")
    op.drop_index("ix_parties_company_id", table_name="parties")
    op.drop_table("parties")
    op.drop_index("ix_import_batches_company_id", table_name="import_batches")
    op.drop_index("ix_import_batches_data_source_id", table_name="import_batches")
    op.drop_table("import_batches")
    op.drop_index("ix_import_profiles_data_source_id", table_name="import_profiles")
    op.drop_table("import_profiles")
    op.drop_index("ix_company_data_sources_status", table_name="company_data_sources")
    op.drop_index("ix_company_data_sources_connector_id", table_name="company_data_sources")
    op.drop_index("ix_company_data_sources_company_id", table_name="company_data_sources")
    op.drop_index("ix_company_data_sources_tenant_id", table_name="company_data_sources")
    op.drop_table("company_data_sources")
