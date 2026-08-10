"""add company memberships

Revision ID: b5a9d0c3e1f2
Revises: 3c61a2d7e4b9
Create Date: 2026-08-10 11:15:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b5a9d0c3e1f2"
down_revision: Union[str, Sequence[str], None] = "3c61a2d7e4b9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "company_memberships",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.String(length=36), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "company_id", name="uq_company_memberships_user_company"),
    )
    op.create_index("ix_company_memberships_user_id", "company_memberships", ["user_id"])
    op.create_index("ix_company_memberships_company_id", "company_memberships", ["company_id"])


def downgrade() -> None:
    op.drop_index("ix_company_memberships_company_id", table_name="company_memberships")
    op.drop_index("ix_company_memberships_user_id", table_name="company_memberships")
    op.drop_table("company_memberships")
