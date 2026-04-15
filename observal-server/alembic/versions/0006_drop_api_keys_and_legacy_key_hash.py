"""Drop api_keys table and users.api_key_hash column.

JWT is now the sole auth mechanism — API keys are no longer used.

Revision ID: 0006
Revises: 0005
Create Date: 2026-04-15
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Drop indexes first
    op.drop_index("idx_api_keys_user_environment", table_name="api_keys")
    op.drop_index("idx_api_keys_active_lookup", table_name="api_keys")
    op.drop_index("idx_api_keys_key_hash", table_name="api_keys")

    # Drop the api_keys table
    op.drop_table("api_keys")

    # Drop the enum type
    op.execute("DROP TYPE IF EXISTS apikeyenvironment")

    # Drop the legacy api_key_hash column from users
    op.drop_column("users", "api_key_hash")


def downgrade() -> None:
    # Re-add the api_key_hash column (nullable since we can't recover data)
    op.add_column("users", sa.Column("api_key_hash", sa.String(64), nullable=True))

    # Re-create the api_keys table
    op.create_table(
        "api_keys",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("key_hash", sa.String(64), nullable=False),
        sa.Column("prefix", sa.String(10), nullable=False),
        sa.Column(
            "environment",
            sa.Enum("live", "test", "dev", name="apikeyenvironment"),
            nullable=False,
            server_default="live",
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_used_ip", sa.String(45), nullable=True),
        sa.Column("scope", sa.JSON, nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("user_id", "name", name="uq_api_keys_user_name"),
        sa.CheckConstraint("length(name) >= 1 AND length(name) <= 100", name="ck_api_keys_name_length"),
    )
    op.create_index("idx_api_keys_key_hash", "api_keys", ["key_hash"])
    op.create_index(
        "idx_api_keys_active_lookup",
        "api_keys",
        ["key_hash", "user_id"],
        postgresql_where=sa.text("revoked_at IS NULL"),
    )
    op.create_index("idx_api_keys_user_environment", "api_keys", ["user_id", "environment"])
