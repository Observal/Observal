# SPDX-FileCopyrightText: 2026 Lokesh Selvam <lokeshselvam7025@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""Add public/private visibility to teamspaces.

Revision ID: 026_team_visibility
Revises: 025_invites
"""

import sqlalchemy as sa

from alembic import op

revision = "026_team_visibility"
down_revision = "025_invites"
branch_labels = None
depends_on = None


def _has_column(table: str, column: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return column in {col["name"] for col in inspector.get_columns(table)}


def upgrade() -> None:
    # Additive and idempotent; every existing teamspace stays public.
    if not _has_column("teams", "is_private"):
        op.add_column(
            "teams",
            sa.Column("is_private", sa.Boolean(), nullable=False, server_default=sa.false()),
        )


def downgrade() -> None:
    if _has_column("teams", "is_private"):
        op.drop_column("teams", "is_private")
