"""Add username column to users table.

Revision ID: 0010
Revises: 0009
Create Date: 2026-04-18
"""

import sqlalchemy as sa

from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    result = conn.execute(
        sa.text("SELECT 1 FROM information_schema.columns WHERE table_name = 'users' AND column_name = 'username'")
    )
    if not result.fetchone():
        op.add_column("users", sa.Column("username", sa.String(32), nullable=True))

    # Check if constraint already exists
    result = conn.execute(
        sa.text(
            "SELECT 1 FROM information_schema.table_constraints "
            "WHERE constraint_name = 'uq_users_username' AND table_name = 'users'"
        )
    )
    if not result.fetchone():
        op.create_unique_constraint("uq_users_username", "users", ["username"])


def downgrade() -> None:
    op.drop_constraint("uq_users_username", "users", type_="unique")
    op.drop_column("users", "username")
