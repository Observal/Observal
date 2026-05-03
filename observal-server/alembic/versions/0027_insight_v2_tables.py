"""Add V2 insight tables: session meta cache, session facets, report columns

Revision ID: 0027
Revises: 0026
Create Date: 2026-05-04 00:00:00.000000

"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "0027"
down_revision: Union[str, Sequence[str], None] = "0026"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create V2 insight tables and extend insight_reports."""
    # Per-session deterministic cache
    op.create_table(
        "insight_session_meta",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("agent_id", sa.UUID(), nullable=False),
        sa.Column("session_id", sa.Text(), nullable=False),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("meta", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("agent_id", "session_id", name="uq_session_meta_agent_session"),
    )
    op.create_index("ix_session_meta_agent", "insight_session_meta", ["agent_id"])

    # Per-session LLM facet cache
    op.create_table(
        "insight_session_facets",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("agent_id", sa.UUID(), nullable=False),
        sa.Column("session_id", sa.Text(), nullable=False),
        sa.Column("extracted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("model_used", sa.String(255), nullable=True),
        sa.Column("facets", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("agent_id", "session_id", name="uq_session_facets_agent_session"),
    )
    op.create_index("ix_session_facets_agent", "insight_session_facets", ["agent_id"])

    # Extend insight_reports for V2
    op.add_column(
        "insight_reports",
        sa.Column("previous_report_id", sa.UUID(), nullable=True),
    )
    op.add_column(
        "insight_reports",
        sa.Column("aggregated_data", sa.JSON(), nullable=True),
    )
    op.add_column(
        "insight_reports",
        sa.Column("report_version", sa.Integer(), server_default="1", nullable=False),
    )
    op.create_foreign_key(
        "fk_insight_reports_previous",
        "insight_reports",
        "insight_reports",
        ["previous_report_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    """Remove V2 insight tables and columns."""
    op.drop_constraint("fk_insight_reports_previous", "insight_reports", type_="foreignkey")
    op.drop_column("insight_reports", "report_version")
    op.drop_column("insight_reports", "aggregated_data")
    op.drop_column("insight_reports", "previous_report_id")

    op.drop_index("ix_session_facets_agent", table_name="insight_session_facets")
    op.drop_table("insight_session_facets")

    op.drop_index("ix_session_meta_agent", table_name="insight_session_meta")
    op.drop_table("insight_session_meta")
