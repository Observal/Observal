# SPDX-FileCopyrightText: 2026 Lokesh Selvam <lokeshselvam7025@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""Add teamspace membership join requests.

Revision ID: 024_team_membership_requests
Revises: 023_inbox
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "024_team_membership_requests"
down_revision = "023_inbox"
branch_labels = None
depends_on = None


JOIN_REQUEST_STATUSES = ("pending", "approved", "rejected", "cancelled")


def _has_table(name: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return name in inspector.get_table_names()


def upgrade() -> None:
    # Additive and idempotent: a partially applied migration must be safe to
    # re-run, matching the convention used by earlier revisions here.
    bind = op.get_bind()

    status_enum = sa.Enum(*JOIN_REQUEST_STATUSES, name="team_join_request_status")
    if bind.dialect.name == "postgresql":
        status_enum.create(bind, checkfirst=True)
        status_enum = postgresql.ENUM(*JOIN_REQUEST_STATUSES, name="team_join_request_status", create_type=False)

    if not _has_table("team_membership_requests"):
        op.create_table(
            "team_membership_requests",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column(
                "team_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("teams.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "user_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("users.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("status", status_enum, nullable=False, server_default="pending"),
            sa.Column("message", sa.String(length=500), nullable=True),
            sa.Column(
                "decided_by",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("users.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("decision_reason", sa.String(length=500), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )
        # One PENDING request per (team, user); decided rows stay as history.
        op.create_index(
            "uq_team_membership_requests_pending",
            "team_membership_requests",
            ["team_id", "user_id"],
            unique=True,
            postgresql_where=sa.text("status = 'pending'"),
            sqlite_where=sa.text("status = 'pending'"),
        )
        op.create_index(
            "ix_team_membership_requests_user_id",
            "team_membership_requests",
            ["user_id"],
        )


def downgrade() -> None:
    if _has_table("team_membership_requests"):
        op.drop_index("ix_team_membership_requests_user_id", table_name="team_membership_requests")
        op.drop_index("uq_team_membership_requests_pending", table_name="team_membership_requests")
        op.drop_table("team_membership_requests")

    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        sa.Enum(name="team_join_request_status").drop(bind, checkfirst=True)
