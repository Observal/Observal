# SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
#
# SPDX-License-Identifier: AGPL-3.0-only

"""Widen grade columns from VARCHAR(2) to VARCHAR(3)

The eval pipeline can produce 'N/A' as a grade when the SLM judge is
unavailable. This is 3 characters and exceeds the original VARCHAR(2).

Revision ID: 0007
Revises: 0006
Create Date: 2026-05-14
"""

import sqlalchemy as sa

from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "scorecards",
        "overall_grade",
        type_=sa.String(3),
        existing_type=sa.String(2),
        existing_nullable=False,
    )
    op.alter_column(
        "scorecards",
        "grade",
        type_=sa.String(3),
        existing_type=sa.String(2),
        existing_nullable=True,
    )
    op.alter_column(
        "scorecard_dimensions",
        "grade",
        type_=sa.String(3),
        existing_type=sa.String(2),
        existing_nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "scorecard_dimensions",
        "grade",
        type_=sa.String(2),
        existing_type=sa.String(3),
        existing_nullable=False,
    )
    op.alter_column(
        "scorecards",
        "grade",
        type_=sa.String(2),
        existing_type=sa.String(3),
        existing_nullable=True,
    )
    op.alter_column(
        "scorecards",
        "overall_grade",
        type_=sa.String(2),
        existing_type=sa.String(3),
        existing_nullable=False,
    )
