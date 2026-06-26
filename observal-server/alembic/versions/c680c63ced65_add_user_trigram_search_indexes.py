# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only
"""add user trigram search indexes

Revision ID: c680c63ced65
Revises: 1a79544a6936
Create Date: 2026-06-26 22:11:00.977521

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c680c63ced65"
down_revision: str | Sequence[str] | None = "1a79544a6936"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.create_index(
        "ix_users_email_trgm",
        "users",
        ["email"],
        unique=False,
        postgresql_using="gin",
        postgresql_ops={"email": "gin_trgm_ops"},
    )
    op.create_index(
        "ix_users_name_trgm",
        "users",
        ["name"],
        unique=False,
        postgresql_using="gin",
        postgresql_ops={"name": "gin_trgm_ops"},
    )
    op.create_index(
        "ix_users_username_trgm",
        "users",
        ["username"],
        unique=False,
        postgresql_using="gin",
        postgresql_ops={"username": "gin_trgm_ops"},
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        "ix_users_username_trgm",
        table_name="users",
        postgresql_using="gin",
        postgresql_ops={"username": "gin_trgm_ops"},
    )
    op.drop_index(
        "ix_users_name_trgm",
        table_name="users",
        postgresql_using="gin",
        postgresql_ops={"name": "gin_trgm_ops"},
    )
    op.drop_index(
        "ix_users_email_trgm",
        table_name="users",
        postgresql_using="gin",
        postgresql_ops={"email": "gin_trgm_ops"},
    )
