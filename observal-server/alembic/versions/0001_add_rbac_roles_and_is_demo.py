"""Add super_admin and reviewer roles, rename developer to reviewer, add is_demo column.

Revision ID: 0001
Revises:
Create Date: 2026-04-13
"""

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add new enum values (idempotent — safe on fresh databases)
    op.execute("ALTER TYPE userrole ADD VALUE IF NOT EXISTS 'super_admin'")
    op.execute("ALTER TYPE userrole ADD VALUE IF NOT EXISTS 'reviewer'")

    # Rename developer -> reviewer in existing rows
    op.execute("UPDATE users SET role = 'reviewer' WHERE role = 'developer'")

    # Add is_demo column (idempotent via IF NOT EXISTS pattern)
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'users' AND column_name = 'is_demo'
            ) THEN
                ALTER TABLE users ADD COLUMN is_demo BOOLEAN NOT NULL DEFAULT false;
            END IF;
        END
        $$;
    """)


def downgrade() -> None:
    # Drop is_demo column
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'users' AND column_name = 'is_demo'
            ) THEN
                ALTER TABLE users DROP COLUMN is_demo;
            END IF;
        END
        $$;
    """)

    # Rename reviewer back to developer in rows
    op.execute("UPDATE users SET role = 'developer' WHERE role = 'reviewer'")
