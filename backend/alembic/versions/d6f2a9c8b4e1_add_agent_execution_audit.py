"""add agent execution audit

Revision ID: d6f2a9c8b4e1
Revises: c3e7a9f2d6b1
Create Date: 2026-08-11 11:30:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d6f2a9c8b4e1"
down_revision: Union[str, Sequence[str], None] = "c3e7a9f2d6b1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "agent_executions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("company_id", sa.String(length=36), nullable=False),
        sa.Column("actor_user_id", sa.Integer(), nullable=True),
        sa.Column("conversation_id", sa.String(length=36), nullable=True),
        sa.Column("agent_id", sa.String(length=64), nullable=False),
        sa.Column("agent_version", sa.String(length=32), nullable=False),
        sa.Column("operation", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("finding_count", sa.Integer(), nullable=False),
        sa.Column("finding_codes", sa.JSON(), nullable=False),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("correlation_id", sa.String(length=64), nullable=True),
        sa.Column("started_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"]),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_agent_executions_tenant_id", "agent_executions", ["tenant_id"])
    op.create_index("ix_agent_executions_company_id", "agent_executions", ["company_id"])
    op.create_index("ix_agent_executions_actor_user_id", "agent_executions", ["actor_user_id"])
    op.create_index("ix_agent_executions_conversation_id", "agent_executions", ["conversation_id"])
    op.create_index("ix_agent_executions_agent_id", "agent_executions", ["agent_id"])
    op.create_index("ix_agent_executions_status", "agent_executions", ["status"])


def downgrade() -> None:
    op.drop_index("ix_agent_executions_status", table_name="agent_executions")
    op.drop_index("ix_agent_executions_agent_id", table_name="agent_executions")
    op.drop_index("ix_agent_executions_conversation_id", table_name="agent_executions")
    op.drop_index("ix_agent_executions_actor_user_id", table_name="agent_executions")
    op.drop_index("ix_agent_executions_company_id", table_name="agent_executions")
    op.drop_index("ix_agent_executions_tenant_id", table_name="agent_executions")
    op.drop_table("agent_executions")
