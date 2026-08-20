"""add user session security state

Revision ID: a7b4c9d2e6f1
Revises: e4b7c1d9f2a6
Create Date: 2026-08-20 15:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "a7b4c9d2e6f1"
down_revision: Union[str, Sequence[str], None] = "e4b7c1d9f2a6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("token_version", sa.Integer(), nullable=False, server_default="0"),
    )
    op.alter_column("users", "token_version", server_default=None)
    op.add_column(
        "users",
        sa.Column("requires_password_change", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.alter_column("users", "requires_password_change", server_default=None)


def downgrade() -> None:
    op.drop_column("users", "requires_password_change")
    op.drop_column("users", "token_version")
