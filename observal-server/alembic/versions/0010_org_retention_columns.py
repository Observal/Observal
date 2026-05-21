# SPDX-FileCopyrightText: 2026 Kaushik Kumar <kaushikrjpm10@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Add data retention columns to organizations table.

Revision ID: 0010
Revises: 0009
Create Date: 2026-05-11
"""

import sqlalchemy as sa

from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("organizations", sa.Column("retention_enabled", sa.Boolean(), server_default="false", nullable=False))
    op.add_column("organizations", sa.Column("data_retention_days", sa.Integer(), nullable=True))
    op.add_column("organizations", sa.Column("score_retention_days", sa.Integer(), nullable=True))
    op.add_column("organizations", sa.Column("max_trace_count", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("organizations", "max_trace_count")
    op.drop_column("organizations", "score_retention_days")
    op.drop_column("organizations", "data_retention_days")
    op.drop_column("organizations", "retention_enabled")
