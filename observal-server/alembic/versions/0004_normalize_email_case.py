"""Normalize email to lowercase and add case-insensitive unique index.

Revision ID: 0004
Revises: 0003
Create Date: 2026-04-15
"""

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Lowercase all existing emails
    op.execute("UPDATE users SET email = LOWER(TRIM(email))")

    # Drop the existing case-sensitive unique constraint and replace with
    # a functional unique index on LOWER(email) so that 'User@Example.com'
    # and 'user@example.com' are treated as the same address.
    op.drop_constraint("users_email_key", "users", type_="unique")
    op.execute("CREATE UNIQUE INDEX ix_users_email_lower ON users (LOWER(email))")


def downgrade() -> None:
    op.execute("DROP INDEX ix_users_email_lower")
    op.create_unique_constraint("users_email_key", "users", ["email"])
