"""add companies and operation audit

Revision ID: d4f8c6a2b9e0
Revises: b5a9d0c3e1f2
Create Date: 2026-08-10 12:30:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d4f8c6a2b9e0"
down_revision: Union[str, Sequence[str], None] = "b5a9d0c3e1f2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _backfill_companies() -> None:
    """Conserva los registros existentes antes de activar las llaves foráneas."""

    op.execute(
        """
        INSERT INTO tenants (id, name, country_code)
        SELECT DISTINCT source.tenant_id, 'Tenant migrado ' || source.tenant_id, 'CO'
        FROM company_data_sources AS source
        WHERE NOT EXISTS (SELECT 1 FROM tenants WHERE tenants.id = source.tenant_id)
        """
    )
    op.execute(
        """
        INSERT INTO companies (id, tenant_id, name, functional_currency)
        SELECT DISTINCT source.company_id, source.tenant_id, 'Empresa migrada ' || source.company_id, 'COP'
        FROM company_data_sources AS source
        WHERE NOT EXISTS (SELECT 1 FROM companies WHERE companies.id = source.company_id)
        """
    )
    for table in ("company_memberships", "import_batches", "parties"):
        op.execute(
            f"""
            INSERT INTO tenants (id, name, country_code)
            SELECT DISTINCT legacy.company_id, 'Tenant migrado ' || legacy.company_id, 'CO'
            FROM {table} AS legacy
            WHERE NOT EXISTS (SELECT 1 FROM companies WHERE companies.id = legacy.company_id)
              AND NOT EXISTS (SELECT 1 FROM tenants WHERE tenants.id = legacy.company_id)
            """
        )
        op.execute(
            f"""
            INSERT INTO companies (id, tenant_id, name, functional_currency)
            SELECT DISTINCT legacy.company_id, legacy.company_id, 'Empresa migrada ' || legacy.company_id, 'COP'
            FROM {table} AS legacy
            WHERE NOT EXISTS (SELECT 1 FROM companies WHERE companies.id = legacy.company_id)
            """
        )


def upgrade() -> None:
    op.create_table(
        "tenants",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("country_code", sa.String(length=2), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "companies",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("functional_currency", sa.String(length=3), nullable=False),
        sa.Column("provider_company_id", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_companies_tenant_id", "companies", ["tenant_id"])

    _backfill_companies()

    op.create_foreign_key(
        "fk_company_memberships_company_id", "company_memberships", "companies", ["company_id"], ["id"], ondelete="CASCADE"
    )
    op.create_foreign_key(
        "fk_company_data_sources_tenant_id", "company_data_sources", "tenants", ["tenant_id"], ["id"]
    )
    op.create_foreign_key(
        "fk_company_data_sources_company_id", "company_data_sources", "companies", ["company_id"], ["id"]
    )
    op.create_foreign_key(
        "fk_import_batches_company_id", "import_batches", "companies", ["company_id"], ["id"]
    )
    op.create_foreign_key(
        "fk_parties_company_id", "parties", "companies", ["company_id"], ["id"]
    )

    op.add_column("company_data_sources", sa.Column("created_by_user_id", sa.Integer(), nullable=True))
    op.add_column("import_batches", sa.Column("created_by_user_id", sa.Integer(), nullable=True))
    op.add_column("parties", sa.Column("created_by_user_id", sa.Integer(), nullable=True))
    op.add_column("parties", sa.Column("updated_by_user_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_company_data_sources_created_by", "company_data_sources", "users", ["created_by_user_id"], ["id"]
    )
    op.create_foreign_key(
        "fk_import_batches_created_by", "import_batches", "users", ["created_by_user_id"], ["id"]
    )
    op.create_foreign_key(
        "fk_parties_created_by", "parties", "users", ["created_by_user_id"], ["id"]
    )
    op.create_foreign_key(
        "fk_parties_updated_by", "parties", "users", ["updated_by_user_id"], ["id"]
    )
    op.create_index("ix_company_data_sources_created_by_user_id", "company_data_sources", ["created_by_user_id"])
    op.create_index("ix_import_batches_created_by_user_id", "import_batches", ["created_by_user_id"])
    op.create_index("ix_parties_created_by_user_id", "parties", ["created_by_user_id"])
    op.create_index("ix_parties_updated_by_user_id", "parties", ["updated_by_user_id"])


def downgrade() -> None:
    op.drop_index("ix_parties_updated_by_user_id", table_name="parties")
    op.drop_index("ix_parties_created_by_user_id", table_name="parties")
    op.drop_index("ix_import_batches_created_by_user_id", table_name="import_batches")
    op.drop_index("ix_company_data_sources_created_by_user_id", table_name="company_data_sources")
    op.drop_constraint("fk_parties_updated_by", "parties", type_="foreignkey")
    op.drop_constraint("fk_parties_created_by", "parties", type_="foreignkey")
    op.drop_constraint("fk_import_batches_created_by", "import_batches", type_="foreignkey")
    op.drop_constraint("fk_company_data_sources_created_by", "company_data_sources", type_="foreignkey")
    op.drop_column("parties", "updated_by_user_id")
    op.drop_column("parties", "created_by_user_id")
    op.drop_column("import_batches", "created_by_user_id")
    op.drop_column("company_data_sources", "created_by_user_id")
    op.drop_constraint("fk_parties_company_id", "parties", type_="foreignkey")
    op.drop_constraint("fk_import_batches_company_id", "import_batches", type_="foreignkey")
    op.drop_constraint("fk_company_data_sources_company_id", "company_data_sources", type_="foreignkey")
    op.drop_constraint("fk_company_data_sources_tenant_id", "company_data_sources", type_="foreignkey")
    op.drop_constraint("fk_company_memberships_company_id", "company_memberships", type_="foreignkey")
    op.drop_index("ix_companies_tenant_id", table_name="companies")
    op.drop_table("companies")
    op.drop_table("tenants")
