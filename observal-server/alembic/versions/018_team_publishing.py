# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""team publishing visibility

Adds the teamspace ownership and privacy axis for the registry: agents gain a
private concept for the first time, and agents, all five component listings, and
component sources gain a team_id.

Revision ID: 018_team_publishing
Revises: 017_teams
Create Date: 2026-08-01 20:20:56.795715

"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "018_team_publishing"
down_revision: Union[str, Sequence[str], None] = "017_teams"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Every table that gains a nullable team_id pointing at teams.id.
_TEAM_TABLES = (
    "agents",
    "mcp_listings",
    "skill_listings",
    "hook_listings",
    "prompt_listings",
    "sandbox_listings",
    "component_sources",
)

# The subset whose team ownership the downgrade guard protects. component_sources
# is excluded: it carries no is_private of its own and follows its listing.
_GUARDED_TABLES = _TEAM_TABLES[:-1]


def upgrade() -> None:
    """Upgrade schema."""
    # Agents had no privacy concept before teamspaces. The five component
    # listings already carry is_private.
    op.add_column("agents", sa.Column("is_private", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.alter_column("agents", "is_private", server_default=None)

    for table in _TEAM_TABLES:
        op.add_column(table, sa.Column("team_id", sa.UUID(), nullable=True))
        op.create_index(f"ix_{table}_team_id", table, ["team_id"], unique=False)
        op.create_foreign_key(
            f"fk_{table}_team_id_teams",
            table,
            "teams",
            ["team_id"],
            ["id"],
            ondelete="SET NULL",
        )

    # This migration deliberately backfills no visibility data.
    #
    # A legacy row with is_private=True and a null team_id predates teamspaces,
    # and the shared helpers in api/deps.py already resolve it without a
    # teamspace: apply_visibility_filter matches such a row only for its creator
    # (submitted_by or created_by), and check_listing_visibility_async returns
    # True only for that creator or for a reviewer, admin, or super_admin.
    # A legacy component_sources row with is_public=False and a null team_id is
    # likewise restricted to reviewers and admins by _source_visible in
    # api/routes/component_source.py.
    #
    # Flipping those rows to public in bulk would therefore fix nothing and
    # would disclose data on every upgrade, and downgrade() cannot undo it
    # because it has no record of which rows it flipped.


def _assert_no_team_owned_rows() -> None:
    """Refuse to downgrade while any listing still belongs to a teamspace.

    Dropping team_id destroys the only record of which teamspace owns a private
    listing, and this downgrade also drops agents.is_private. Re-upgrading
    afterwards recreates is_private with a false server default, so every agent a
    teamspace kept private comes back public, and every surviving private listing
    comes back with a null team_id that its team can no longer reach. Rather than
    let a rollback silently disclose or orphan private rows, stop and make the
    operator move or delete team-owned rows first.
    """
    conn = op.get_bind()
    owned = {}
    for table in _GUARDED_TABLES:
        count = conn.execute(sa.text(f"SELECT count(*) FROM {table} WHERE team_id IS NOT NULL")).scalar_one()
        if count:
            owned[table] = count
    if owned:
        detail = ", ".join(f"{table}={count}" for table, count in sorted(owned.items()))
        raise RuntimeError(
            "Cannot downgrade 018_team_publishing: team-owned listings still exist "
            f"({detail}). Reassign or delete them before rolling back, otherwise "
            "their teamspace ownership is lost and a later re-upgrade cannot restore it."
        )


def downgrade() -> None:
    """Downgrade schema."""
    _assert_no_team_owned_rows()
    for table in reversed(_TEAM_TABLES):
        op.drop_constraint(f"fk_{table}_team_id_teams", table, type_="foreignkey")
        op.drop_index(f"ix_{table}_team_id", table_name=table)
        op.drop_column(table, "team_id")
    op.drop_column("agents", "is_private")
