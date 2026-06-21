# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""soft delete agents

Revision ID: 1caa45d85720
Revises: 010_global_unique_names
Create Date: 2026-06-21 16:35:54.480327

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "1caa45d85720"
down_revision: str | Sequence[str] | None = "010_global_unique_names"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("agents", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
    op.drop_constraint("uq_agents_name", "agents", type_="unique")
    op.create_index(
        "uq_agents_active_name",
        "agents",
        ["name"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
        sqlite_where=sa.text("deleted_at IS NULL"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        "uq_agents_active_name",
        table_name="agents",
        postgresql_where=sa.text("deleted_at IS NULL"),
        sqlite_where=sa.text("deleted_at IS NULL"),
    )
    op.create_unique_constraint("uq_agents_name", "agents", ["name"])
    op.drop_column("agents", "deleted_at")
