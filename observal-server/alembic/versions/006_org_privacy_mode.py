# SPDX-FileCopyrightText: 2026 Nav-Prak <naveenprakaasam@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Add privacy_mode to organizations.

Ingest data-minimization mode: full | redacted | metadata_only | disabled_raw.
Defaults to 'full' so existing organizations keep their current behavior.

Revision ID: 006_org_privacy_mode
Revises: 005_insight_self_learn
Create Date: 2026-05-30
"""

import sqlalchemy as sa

from alembic import op

revision = "006_org_privacy_mode"
down_revision = "005_insight_self_learn"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "organizations",
        sa.Column("privacy_mode", sa.String(length=32), nullable=False, server_default="full"),
    )


def downgrade() -> None:
    op.drop_column("organizations", "privacy_mode")
