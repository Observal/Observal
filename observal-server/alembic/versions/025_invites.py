# SPDX-FileCopyrightText: 2026 Lokesh Selvam <lokeshselvam7025@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""Add admin-minted invite links and their redemption audit trail.

Revision ID: 025_invites
Revises: 024_team_membership_requests
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "025_invites"
down_revision = "024_team_membership_requests"
branch_labels = None
depends_on = None


def _has_table(name: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return name in inspector.get_table_names()


def upgrade() -> None:
    # Additive and idempotent: a partially applied migration must be safe to
    # re-run, matching the convention used by earlier revisions here.
    if not _has_table("invites"):
        op.create_table(
            "invites",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column("token_hash", sa.String(length=64), nullable=False),
            sa.Column(
                "invited_by",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("users.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("max_uses", sa.Integer(), nullable=True),
            sa.Column("use_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("next_path", sa.String(length=500), nullable=True),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("token_hash", name="uq_invites_token_hash"),
        )
        op.create_index("ix_invites_invited_by", "invites", ["invited_by"])

    if not _has_table("invite_redemptions"):
        op.create_table(
            "invite_redemptions",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column(
                "invite_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("invites.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "user_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("users.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index("ix_invite_redemptions_invite_id", "invite_redemptions", ["invite_id"])


def downgrade() -> None:
    if _has_table("invite_redemptions"):
        op.drop_index("ix_invite_redemptions_invite_id", table_name="invite_redemptions")
        op.drop_table("invite_redemptions")
    if _has_table("invites"):
        op.drop_index("ix_invites_invited_by", table_name="invites")
        op.drop_table("invites")
