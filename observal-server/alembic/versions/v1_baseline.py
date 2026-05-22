# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""v1.0 baseline schema stamp.

This is a no-op migration that serves as the baseline revision for v1.0.
The actual schema is created by the init container (entrypoint.sh) using
Base.metadata.create_all before Alembic runs.

For existing pre-1.0 installations:
    1. Ensure the schema matches v1.0 models (it should if you were on latest pre-1.0)
    2. Run: alembic stamp v1_baseline

For fresh installations:
    The init container creates all tables, then stamps this revision automatically.

Revision ID: v1_baseline
Revises:
Create Date: 2026-05-22 00:00:00.000000
"""

revision = "v1_baseline"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    """No-op: schema created by init container before Alembic runs."""
    pass


def downgrade() -> None:
    """No-op: use Base.metadata.drop_all() manually if needed."""
    pass
