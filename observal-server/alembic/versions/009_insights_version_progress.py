# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Add version scope and progress fields to insight reports.

Revision ID: 009_insights_version_progress
Revises: 008_remove_invites
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op

revision = "009_insights_version_progress"
down_revision = "008_remove_invites"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("insight_reports", sa.Column("agent_version_id", UUID(as_uuid=True), nullable=True))
    op.add_column("insight_reports", sa.Column("agent_version", sa.String(50), nullable=True))
    op.add_column(
        "insight_reports",
        sa.Column("version_scope", sa.String(50), nullable=True, server_default="canonical_and_dirty"),
    )
    op.add_column("insight_reports", sa.Column("comparison_agent_version_id", UUID(as_uuid=True), nullable=True))
    op.add_column("insight_reports", sa.Column("comparison_agent_version", sa.String(50), nullable=True))
    op.add_column("insight_reports", sa.Column("progress_phase", sa.String(50), nullable=True, server_default="queued"))
    op.add_column("insight_reports", sa.Column("progress_current", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("insight_reports", sa.Column("progress_total", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("insight_reports", sa.Column("progress_percent", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("insight_reports", sa.Column("progress_message", sa.Text(), nullable=True))
    op.add_column("insight_reports", sa.Column("progress_updated_at", sa.DateTime(timezone=True), nullable=True))

    op.create_foreign_key(
        "fk_insight_reports_agent_version_id",
        "insight_reports",
        "agent_versions",
        ["agent_version_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_insight_reports_comparison_agent_version_id",
        "insight_reports",
        "agent_versions",
        ["comparison_agent_version_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_insight_reports_agent_version_id", "insight_reports", ["agent_version_id"])
    op.create_index("ix_insight_reports_agent_version", "insight_reports", ["agent_version"])


def downgrade() -> None:
    op.drop_index("ix_insight_reports_agent_version", table_name="insight_reports")
    op.drop_index("ix_insight_reports_agent_version_id", table_name="insight_reports")
    op.drop_constraint("fk_insight_reports_comparison_agent_version_id", "insight_reports", type_="foreignkey")
    op.drop_constraint("fk_insight_reports_agent_version_id", "insight_reports", type_="foreignkey")
    op.drop_column("insight_reports", "progress_updated_at")
    op.drop_column("insight_reports", "progress_message")
    op.drop_column("insight_reports", "progress_percent")
    op.drop_column("insight_reports", "progress_total")
    op.drop_column("insight_reports", "progress_current")
    op.drop_column("insight_reports", "progress_phase")
    op.drop_column("insight_reports", "comparison_agent_version")
    op.drop_column("insight_reports", "comparison_agent_version_id")
    op.drop_column("insight_reports", "version_scope")
    op.drop_column("insight_reports", "agent_version")
    op.drop_column("insight_reports", "agent_version_id")
