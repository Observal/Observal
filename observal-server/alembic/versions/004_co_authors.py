# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Add co_authors JSON column to agents and component listing tables.

Renames agents.co_maintainers -> agents.co_authors for consistency.
Adds co_authors (JSON, default []) to mcp_listings, hook_listings,
sandbox_listings, prompt_listings.

Revision ID: 004_co_authors
Revises: 003_skill_registry_direct
Create Date: 2026-05-27
"""

import sqlalchemy as sa

from alembic import op

revision = "004_co_authors"
down_revision = "003_skill_registry_direct"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Rename co_maintainers -> co_authors on agents table
    op.alter_column("agents", "co_maintainers", new_column_name="co_authors")

    # Add co_authors to all component listing tables
    for table in ("mcp_listings", "hook_listings", "sandbox_listings", "prompt_listings", "skill_listings"):
        op.add_column(table, sa.Column("co_authors", sa.JSON(), server_default="[]", nullable=False))


def downgrade() -> None:
    for table in ("skill_listings", "prompt_listings", "sandbox_listings", "hook_listings", "mcp_listings"):
        op.drop_column(table, "co_authors")

    op.alter_column("agents", "co_authors", new_column_name="co_maintainers")
