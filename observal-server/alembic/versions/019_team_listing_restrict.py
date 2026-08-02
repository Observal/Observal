# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""restrict teamspace deletion while listings reference it

018 created the team_id foreign keys with ON DELETE SET NULL, which made deleting
a teamspace silently strip its listings: is_private stayed true, team_id went
null, and every member except the original submitter lost access. The application
guard added afterwards counts rows and then deletes, which is racy, because a
publish landing between the count and the delete is orphaned anyway.

RESTRICT moves the rule into the database, where the check and the delete are the
same statement. The guard stays as a pre-check so the API can answer with a
useful message instead of an integrity error.

Revision ID: 019_team_listing_restrict
Revises: 018_team_publishing
Create Date: 2026-08-02 11:40:00.000000

"""

from collections.abc import Sequence
from typing import Union

from alembic import op

revision: str = "019_team_listing_restrict"
down_revision: Union[str, Sequence[str], None] = "018_team_publishing"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TEAM_TABLES = (
    "agents",
    "mcp_listings",
    "skill_listings",
    "hook_listings",
    "prompt_listings",
    "sandbox_listings",
    "component_sources",
)


def _recreate(ondelete: str) -> None:
    for table in _TEAM_TABLES:
        op.drop_constraint(f"fk_{table}_team_id_teams", table, type_="foreignkey")
        op.create_foreign_key(
            f"fk_{table}_team_id_teams",
            table,
            "teams",
            ["team_id"],
            ["id"],
            ondelete=ondelete,
        )


def upgrade() -> None:
    """Upgrade schema."""
    _recreate("RESTRICT")


def downgrade() -> None:
    """Downgrade schema."""
    _recreate("SET NULL")
