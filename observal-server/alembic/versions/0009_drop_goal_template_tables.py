# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""drop agent_goal_templates and agent_goal_sections tables

Revision ID: 0009
Revises: 0008
Create Date: 2026-05-19
"""

import sqlalchemy as sa

from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_table("agent_goal_sections")
    op.drop_table("agent_goal_templates")


def downgrade() -> None:
    op.create_table(
        "agent_goal_templates",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("agent_version_id", sa.Uuid(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["agent_version_id"], ["agent_versions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("agent_version_id"),
    )
    op.create_table(
        "agent_goal_sections",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("goal_template_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("grounding_required", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("order", sa.Integer(), nullable=False, server_default="0"),
        sa.ForeignKeyConstraint(["goal_template_id"], ["agent_goal_templates.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
