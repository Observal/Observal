# SPDX-FileCopyrightText: 2026 Kaushik <kaushikrjpm10@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""Repair share tables for installations stamped by the former skill-only branch.

Revision ID: 038_share_compat
Revises: 037_recommended_compat

Fresh installations run upstream 030_agent_share_manifests before the skill
revisions. Older installations already stamped past that new ancestor never
replay it; install both missing share tables without modifying any share data.
Refuse a partial schema rather than silently completing an ambiguous state.
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "038_share_compat"
down_revision = "037_recommended_compat"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    manifests = inspector.has_table("agent_share_manifests")
    items = inspector.has_table("agent_share_items")
    if manifests != items:
        raise RuntimeError("Partial agent share schema; repair manually before upgrading")
    if manifests:
        return  # The upstream 030 revision already created both tables.

    op.create_table(
        "agent_share_manifests",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(length=120), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_index("ix_agent_share_manifests_created_by", "agent_share_manifests", ["created_by"])
    op.create_index("ix_agent_share_manifests_expires_at", "agent_share_manifests", ["expires_at"])

    op.create_table(
        "agent_share_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("manifest_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("agent_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("agent_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["agent_version_id"], ["agent_versions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["manifest_id"], ["agent_share_manifests.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("manifest_id", "agent_id", "agent_version_id", name="uq_agent_share_item_version"),
        sa.UniqueConstraint("manifest_id", "position", name="uq_agent_share_item_position"),
    )
    op.create_index("ix_agent_share_items_agent_id", "agent_share_items", ["agent_id"])


def downgrade() -> None:
    # Upstream 030 owns the tables on a fresh schema; leave branch-stamped
    # tables intact on rollback. Downgrading past 030 will remove them there.
    pass
