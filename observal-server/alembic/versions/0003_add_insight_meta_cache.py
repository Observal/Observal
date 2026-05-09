"""Add insight_meta_cache table for batch session metadata caching.

Revision ID: 0003
Revises: 0002
Create Date: 2026-05-09
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "insight_meta_cache",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("agent_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("agents.id"), nullable=False),
        sa.Column("period_start", sa.String(30), nullable=False),
        sa.Column("period_end", sa.String(30), nullable=False),
        sa.Column("session_metas", postgresql.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("agent_id", "period_start", "period_end", name="uq_meta_cache_agent_period"),
    )


def downgrade() -> None:
    op.drop_table("insight_meta_cache")
