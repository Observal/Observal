"""Add agent review statuses, component bundles, and archive support.

- Extend AgentStatus enum with 'pending' and 'rejected'
- Extend ListingStatus enum with 'archived'
- Create component_bundles table for MCP-linked skills
- Add bundle_id FK to all 5 listing tables
- Add rejection_reason column to agents

Revision ID: 0011
Revises: 0010
Create Date: 2026-04-17
"""

from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None

_LISTING_TABLES = [
    "mcp_listings",
    "skill_listings",
    "hook_listings",
    "prompt_listings",
    "sandbox_listings",
]


def upgrade() -> None:
    # Enum extensions must run outside a transaction in PostgreSQL
    op.execute("COMMIT")
    op.execute("ALTER TYPE agentstatus ADD VALUE IF NOT EXISTS 'pending'")
    op.execute("ALTER TYPE agentstatus ADD VALUE IF NOT EXISTS 'rejected'")
    op.execute("ALTER TYPE listingstatus ADD VALUE IF NOT EXISTS 'archived'")
    op.execute("BEGIN")

    # Component bundles table
    op.execute("""
        CREATE TABLE IF NOT EXISTS component_bundles (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            name VARCHAR(255) NOT NULL,
            description TEXT DEFAULT '',
            submitted_by UUID NOT NULL REFERENCES users(id),
            created_at TIMESTAMPTZ DEFAULT NOW()
        )
    """)

    # Add bundle_id FK + index to each listing table
    for table in _LISTING_TABLES:
        op.execute(f"""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name = '{table}' AND column_name = 'bundle_id'
                ) THEN
                    ALTER TABLE {table}
                    ADD COLUMN bundle_id UUID REFERENCES component_bundles(id);
                END IF;
            END $$;
        """)
        op.execute(f"""
            CREATE INDEX IF NOT EXISTS ix_{table}_bundle_id ON {table}(bundle_id)
        """)

    # Add rejection_reason to agents
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'agents' AND column_name = 'rejection_reason'
            ) THEN
                ALTER TABLE agents ADD COLUMN rejection_reason TEXT;
            END IF;
        END $$;
    """)

    # Index on agents.status for review queries
    op.execute("CREATE INDEX IF NOT EXISTS ix_agents_status ON agents(status)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_agents_status")
    op.execute("ALTER TABLE agents DROP COLUMN IF EXISTS rejection_reason")
    for table in _LISTING_TABLES:
        op.execute(f"DROP INDEX IF EXISTS ix_{table}_bundle_id")
        op.execute(f"ALTER TABLE {table} DROP COLUMN IF EXISTS bundle_id")
    op.execute("DROP TABLE IF EXISTS component_bundles")
