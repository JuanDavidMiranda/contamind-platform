"""add DIAN acquirer lookup audit

Revision ID: e4b7c1d9f2a6
Revises: d8f2a5c9e3b4
Create Date: 2026-08-19 10:30:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "e4b7c1d9f2a6"
down_revision: Union[str, Sequence[str], None] = "d8f2a5c9e3b4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "dian_acquirer_lookups",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("data_source_id", sa.String(length=36), nullable=False),
        sa.Column("company_id", sa.String(length=36), nullable=False),
        sa.Column("actor_user_id", sa.Integer(), nullable=False),
        sa.Column("document_type", sa.String(length=10), nullable=False),
        sa.Column("document_number_hmac", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("correlation_id", sa.String(length=64), nullable=True),
        sa.Column("requested_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"]),
        sa.ForeignKeyConstraint(["data_source_id"], ["company_data_sources.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_dian_acquirer_lookups_data_source_id", "dian_acquirer_lookups", ["data_source_id"])
    op.create_index("ix_dian_acquirer_lookups_company_id", "dian_acquirer_lookups", ["company_id"])
    op.create_index("ix_dian_acquirer_lookups_actor_user_id", "dian_acquirer_lookups", ["actor_user_id"])
    op.create_index("ix_dian_acquirer_lookups_status", "dian_acquirer_lookups", ["status"])


def downgrade() -> None:
    op.drop_index("ix_dian_acquirer_lookups_status", table_name="dian_acquirer_lookups")
    op.drop_index("ix_dian_acquirer_lookups_actor_user_id", table_name="dian_acquirer_lookups")
    op.drop_index("ix_dian_acquirer_lookups_company_id", table_name="dian_acquirer_lookups")
    op.drop_index("ix_dian_acquirer_lookups_data_source_id", table_name="dian_acquirer_lookups")
    op.drop_table("dian_acquirer_lookups")
