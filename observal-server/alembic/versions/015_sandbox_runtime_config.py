# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Add sandbox runtime_config.

Revision ID: 015_sandbox_runtime_config
Revises: 011_migration_jobs
"""

import sqlalchemy as sa

from alembic import op

revision = "015_sandbox_runtime_config"
down_revision = "011_migration_jobs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("sandbox_versions", sa.Column("runtime_config", sa.JSON(), nullable=False, server_default="{}"))
    op.alter_column("sandbox_versions", "runtime_config", server_default=None)


def downgrade() -> None:
    op.drop_column("sandbox_versions", "runtime_config")
