# SPDX-FileCopyrightText: 2026 Lokesh Selvam <lokeshselvam7025@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""Add local usage-ping delivery state.

Revision ID: 026_usage_ping_state
Revises: 025_team_visibility_review
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "026_usage_ping_state"
down_revision = "025_team_visibility_review"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "usage_ping_state" in inspector.get_table_names():
        return
    op.create_table(
        "usage_ping_state",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("installation_id", sa.UUID(), nullable=False),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.String(length=500), nullable=True),
        sa.Column("last_payload", postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column("last_response", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("installation_id"),
    )


def downgrade() -> None:
    op.drop_table("usage_ping_state")
