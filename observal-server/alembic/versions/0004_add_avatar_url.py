# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only
"""Add users.avatar_url TEXT column for user profile pictures

Supports base64 data URLs for user-uploaded profile pictures. Nullable to
allow users without avatars (shows initials instead).

Revision ID: 0004
Revises: 0003
Create Date: 2026-05-10
"""

import sqlalchemy as sa

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Idempotent: check if column exists before adding
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {c["name"] for c in inspector.get_columns("users")}
    if "avatar_url" not in columns:
        op.add_column(
            "users",
            sa.Column(
                "avatar_url",
                sa.Text(),
                nullable=True,
            ),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {c["name"] for c in inspector.get_columns("users")}
    if "avatar_url" in columns:
        op.drop_column("users", "avatar_url")
