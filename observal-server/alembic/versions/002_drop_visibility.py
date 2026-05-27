# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Drop agent visibility and team access.

Revision ID: 002_drop_visibility
Revises: v1_baseline
Create Date: 2026-05-26
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op

revision = "002_drop_visibility"
down_revision = "v1_baseline"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_table("agent_team_access")
    op.drop_column("agents", "visibility")
    op.execute("DROP TYPE IF EXISTS agentvisibility")


def downgrade() -> None:
    op.execute("CREATE TYPE agentvisibility AS ENUM ('public', 'private')")
    op.add_column(
        "agents",
        sa.Column("visibility", sa.Enum("public", "private", name="agentvisibility"), server_default="public"),
    )
    op.create_table(
        "agent_team_access",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("agent_id", UUID(as_uuid=True), sa.ForeignKey("agents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("group_name", sa.String(255), nullable=False),
        sa.Column("permission", sa.String(50), nullable=False),
    )
