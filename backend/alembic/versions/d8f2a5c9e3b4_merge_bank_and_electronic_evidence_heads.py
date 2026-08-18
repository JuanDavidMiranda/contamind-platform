"""merge bank and electronic evidence heads

Revision ID: d8f2a5c9e3b4
Revises: a1c4e7f9b2d6, c7e1f4a8b2d3
Create Date: 2026-08-18 11:15:00.000000
"""

from typing import Sequence, Union


revision: str = "d8f2a5c9e3b4"
down_revision: Union[str, Sequence[str], None] = ("a1c4e7f9b2d6", "c7e1f4a8b2d3")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
