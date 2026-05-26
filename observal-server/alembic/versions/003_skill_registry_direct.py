# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Add registry_direct delivery mode fields to skill_versions.

Revision ID: 003_skill_registry_direct
Revises: 002_drop_visibility
Create Date: 2026-05-26
"""

import sqlalchemy as sa

from alembic import op

revision = "003_skill_registry_direct"
down_revision = "002_drop_visibility"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "skill_versions", sa.Column("delivery_mode", sa.String(20), server_default="git_fetch", nullable=False)
    )
    op.add_column("skill_versions", sa.Column("script_content", sa.Text(), nullable=True))
    op.add_column("skill_versions", sa.Column("script_filename", sa.String(255), nullable=True))


def downgrade() -> None:
    op.drop_column("skill_versions", "script_filename")
    op.drop_column("skill_versions", "script_content")
    op.drop_column("skill_versions", "delivery_mode")
