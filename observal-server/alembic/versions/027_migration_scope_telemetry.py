# SPDX-FileCopyrightText: 2026 Observal contributors
# SPDX-FileCopyrightText: 2026 Srihari <sriharilegend23@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""Rename the migration scope value 'clickhouse' to 'telemetry'.

The analytics store is DuckDB, so the persisted scope label for a
telemetry-only move no longer names the old engine. Postgres rewrites the enum
value in place, which keeps existing migration job rows valid.

Revision ID: 027_migration_scope_telemetry
Revises: 026_usage_ping_state
"""

from alembic import op

revision = "027_migration_scope_telemetry"
down_revision = "026_usage_ping_state"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TYPE migration_scope RENAME VALUE 'clickhouse' TO 'telemetry'")


def downgrade() -> None:
    op.execute("ALTER TYPE migration_scope RENAME VALUE 'telemetry' TO 'clickhouse'")
