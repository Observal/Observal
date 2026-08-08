# SPDX-FileCopyrightText: 2026 Lokesh Selvam <lokeshselvam7025@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""Mark each user's one personal teamspace.

Revision ID: 027_personal_teamspace
Revises: 026_team_visibility
"""

import sqlalchemy as sa

from alembic import op

revision = "027_personal_teamspace"
down_revision = "026_team_visibility"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "teams",
        sa.Column("is_personal", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_index(
        "uq_teams_personal_created_by",
        "teams",
        ["created_by"],
        unique=True,
        postgresql_where=sa.text("is_personal"),
        sqlite_where=sa.text("is_personal = 1"),
    )


def downgrade() -> None:
    op.drop_index("uq_teams_personal_created_by", table_name="teams")
    op.drop_column("teams", "is_personal")
