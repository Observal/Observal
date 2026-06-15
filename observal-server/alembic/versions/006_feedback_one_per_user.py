# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Add unique constraint, anonymous flag, and updated_at to feedback.

Revision ID: 006
Revises: 005_insight_self_learn
"""

import sqlalchemy as sa

from alembic import op

revision = "006_feedback_one_per_user"
down_revision = "005_insight_self_learn"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("feedback", sa.Column("anonymous", sa.Boolean(), server_default="false", nullable=False))
    op.add_column("feedback", sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True))
    op.create_unique_constraint("uq_feedback_user_listing", "feedback", ["user_id", "listing_id", "listing_type"])


def downgrade() -> None:
    op.drop_constraint("uq_feedback_user_listing", "feedback", type_="unique")
    op.drop_column("feedback", "updated_at")
    op.drop_column("feedback", "anonymous")
