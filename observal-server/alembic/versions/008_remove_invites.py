# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Remove invites table after VSA cleanup.

Revision ID: 008_remove_invites
Revises: 007_invites
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op

revision = "008_remove_invites"
down_revision = "007_invites"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_table("invites")
    op.execute("DROP TYPE IF EXISTS invitechannel")


def downgrade() -> None:
    op.create_table(
        "invites",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "org_id",
            UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("email", sa.String(255), nullable=True),
        sa.Column(
            "role",
            sa.Enum("super_admin", "admin", "reviewer", "user", name="userrole", create_type=False),
            nullable=False,
        ),
        sa.Column(
            "channel",
            sa.Enum("email", "link", name="invitechannel"),
            nullable=False,
        ),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("invited_by", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("accepted_by", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("revoked", sa.Boolean(), server_default="false", nullable=False),
    )
