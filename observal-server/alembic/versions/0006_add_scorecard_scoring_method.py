# SPDX-FileCopyrightText: 2026 Swathi Saravanan <ss4522@cornell.edu>
#
# SPDX-License-Identifier: AGPL-3.0-only

"""Add scoring_method + checks_json to scorecards

Revision ID: 0006
Revises: 0005
Create Date: 2026-05-08
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {c["name"] for c in inspector.get_columns("scorecards")}
    if "scoring_method" not in columns:
        op.add_column(
            "scorecards",
            sa.Column("scoring_method", sa.String(32), nullable=False, server_default="legacy_deductive"),
        )
    if "checks_json" not in columns:
        op.add_column("scorecards", sa.Column("checks_json", postgresql.JSON(), nullable=True))
    op.create_index(
        "ix_scorecards_scoring_method",
        "scorecards",
        ["scoring_method"],
        unique=False,
        if_not_exists=True,
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {c["name"] for c in inspector.get_columns("scorecards")}
    op.drop_index("ix_scorecards_scoring_method", table_name="scorecards", if_exists=True)
    if "checks_json" in columns:
        op.drop_column("scorecards", "checks_json")
    if "scoring_method" in columns:
        op.drop_column("scorecards", "scoring_method")
