# SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""Add self-learn columns to insight_reports.

Adds applied_at (timestamptz) and applied_items (jsonb) to track
when insight suggestions were materialized into registry items.

Revision ID: 005_insight_self_learn
Revises: 004_co_authors
Create Date: 2026-05-28
"""

import sqlalchemy as sa

from alembic import op

revision = "005_insight_self_learn"
down_revision = "004_co_authors"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("insight_reports", sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("insight_reports", sa.Column("applied_items", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("insight_reports", "applied_items")
    op.drop_column("insight_reports", "applied_at")
