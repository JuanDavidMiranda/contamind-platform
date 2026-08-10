"""add tenant ownership and company lifecycle

Revision ID: e7c3f9b1a4d6
Revises: d4f8c6a2b9e0
Create Date: 2026-08-10 13:40:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e7c3f9b1a4d6"
down_revision: Union[str, Sequence[str], None] = "d4f8c6a2b9e0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "companies",
        sa.Column("status", sa.String(length=20), server_default="active", nullable=False),
    )
    op.create_index("ix_companies_status", "companies", ["status"])
    op.create_table(
        "tenant_memberships",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "tenant_id", name="uq_tenant_memberships_user_tenant"),
    )
    op.create_index("ix_tenant_memberships_user_id", "tenant_memberships", ["user_id"])
    op.create_index("ix_tenant_memberships_tenant_id", "tenant_memberships", ["tenant_id"])
    op.execute(
        """
        INSERT INTO tenant_memberships (user_id, tenant_id, role)
        SELECT DISTINCT membership.user_id, company.tenant_id, 'owner'
        FROM company_memberships AS membership
        JOIN companies AS company ON company.id = membership.company_id
        WHERE membership.role = 'owner'
          AND NOT EXISTS (
              SELECT 1
              FROM tenant_memberships AS tenant_membership
              WHERE tenant_membership.user_id = membership.user_id
                AND tenant_membership.tenant_id = company.tenant_id
          )
        """
    )


def downgrade() -> None:
    op.drop_index("ix_tenant_memberships_tenant_id", table_name="tenant_memberships")
    op.drop_index("ix_tenant_memberships_user_id", table_name="tenant_memberships")
    op.drop_table("tenant_memberships")
    op.drop_index("ix_companies_status", table_name="companies")
    op.drop_column("companies", "status")
