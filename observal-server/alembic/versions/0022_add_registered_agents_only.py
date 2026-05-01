"""add registered_agents_only column to organizations

When enabled, only registered (active) agents are traced.
Unregistered agent telemetry is stored as metadata-only (no content).

Revision ID: 0022
Revises: 0021
Create Date: 2026-05-01 00:00:00.000000

"""

from collections.abc import Sequence
from typing import Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0022"
down_revision: Union[str, Sequence[str], None] = "0021"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add registered_agents_only toggle to organizations."""
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'organizations' AND column_name = 'registered_agents_only'
            ) THEN
                ALTER TABLE organizations ADD COLUMN registered_agents_only BOOLEAN NOT NULL DEFAULT FALSE;
            END IF;
        END
        $$;
    """)


def downgrade() -> None:
    """Remove registered_agents_only column."""
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'organizations' AND column_name = 'registered_agents_only'
            ) THEN
                ALTER TABLE organizations DROP COLUMN registered_agents_only;
            END IF;
        END
        $$;
    """)
