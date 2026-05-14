# SPDX-FileCopyrightText: 2026 Swathi Saravanan <ss4522@cornell.edu>
#
# SPDX-License-Identifier: AGPL-3.0-only

"""Add scoring_method + checks_json to scorecards

Revision ID: 0003
Revises: 0002
Create Date: 2026-05-08
"""

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE scorecards ADD COLUMN IF NOT EXISTS scoring_method VARCHAR(32) NOT NULL DEFAULT 'legacy_deductive'"
    )
    op.execute("ALTER TABLE scorecards ADD COLUMN IF NOT EXISTS checks_json JSON")
    op.execute("CREATE INDEX IF NOT EXISTS ix_scorecards_scoring_method ON scorecards (scoring_method)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_scorecards_scoring_method")
    op.execute("ALTER TABLE scorecards DROP COLUMN IF EXISTS checks_json")
    op.execute("ALTER TABLE scorecards DROP COLUMN IF EXISTS scoring_method")
