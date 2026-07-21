# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""Add canonical user namespaces to registry listings.

Revision ID: 016_registry_publish_loop
Revises: 015_sandbox_runtime_config
"""

import sqlalchemy as sa

from alembic import op

revision = "016_registry_publish_loop"
down_revision = "015_sandbox_runtime_config"
branch_labels = None
depends_on = None

_TABLES = {
    "agents": "created_by",
    "hook_listings": "submitted_by",
    "mcp_listings": "submitted_by",
    "prompt_listings": "submitted_by",
    "sandbox_listings": "submitted_by",
    "skill_listings": "submitted_by",
}
_COMPONENT_TABLES = tuple(table for table in _TABLES if table != "agents")
_RESERVED_SLUGS = (
    "archive",
    "draft",
    "install",
    "resolve",
    "restore",
    "submit",
    "unarchive",
    "versions",
)


def _backfill_usernames() -> None:
    op.execute(
        """
        DO $$
        DECLARE
            row RECORD;
            candidate TEXT;
            attempt INTEGER;
        BEGIN
            FOR row IN SELECT id FROM users WHERE username IS NULL ORDER BY id LOOP
                attempt := 0;
                LOOP
                    candidate := 'u' || substr(md5(row.id::text || ':' || attempt::text), 1, 31);
                    EXIT WHEN NOT EXISTS (SELECT 1 FROM users WHERE username = candidate);
                    attempt := attempt + 1;
                END LOOP;
                UPDATE users SET username = candidate WHERE id = row.id;
            END LOOP;
        END $$;
        """
    )


def _backfill_listing(table: str, creator_column: str) -> None:
    # A missing creator means ownership cannot be reconstructed safely. PostgreSQL
    # FKs normally make this impossible, but imported databases may have disabled them.
    op.execute(
        f"""
        DO $$
        DECLARE orphan_id UUID;
        BEGIN
            SELECT listing.id INTO orphan_id
            FROM {table} AS listing
            LEFT JOIN users ON users.id = listing.{creator_column}
            WHERE users.id IS NULL
            LIMIT 1;
            IF orphan_id IS NOT NULL THEN
                RAISE EXCEPTION 'Cannot backfill {table} namespace: orphaned listing %', orphan_id;
            END IF;
        END $$;
        """
    )
    reserved = ", ".join(f"'{word}'" for word in _RESERVED_SLUGS)
    op.execute(
        f"""
        WITH normalized AS (
            SELECT listing.id,
                   users.username AS namespace,
                   trim(both '-_' from regexp_replace(lower(listing.name), '[^a-z0-9_-]+', '-', 'g')) AS value
            FROM {table} AS listing
            JOIN users ON users.id = listing.{creator_column}
        ), generated AS (
            SELECT id,
                   namespace,
                   CASE
                       WHEN value = '' THEN 'item-' || left(replace(id::text, '-', ''), 8)
                       WHEN value !~ '^[a-z0-9]' THEN 'item-' || value
                       ELSE value
                   END AS clean_slug
            FROM normalized
        )
        UPDATE {table} AS listing
        SET namespace = generated.namespace,
            slug = left(
                CASE
                    WHEN generated.clean_slug IN ({reserved})
                        THEN generated.clean_slug || '-' || left(replace(listing.id::text, '-', ''), 8)
                    ELSE generated.clean_slug
                END,
                64
            )
        FROM generated
        WHERE generated.id = listing.id
        """
    )


def _dedupe_names_for_downgrade(table: str, *, active_only: bool = False) -> None:
    active_filter = "WHERE deleted_at IS NULL" if active_only else ""
    op.execute(
        f"""
        WITH ranked AS (
            SELECT id, row_number() OVER (PARTITION BY name ORDER BY created_at, id) AS rn
            FROM {table}
            {active_filter}
        )
        UPDATE {table} AS target
        SET name = left(target.name || '-' || left(replace(target.id::text, '-', ''), 8), 255)
        FROM ranked
        WHERE target.id = ranked.id AND ranked.rn > 1
        """
    )


def upgrade() -> None:
    for table in _TABLES:
        op.add_column(table, sa.Column("namespace", sa.String(32), nullable=True))
        op.add_column(table, sa.Column("slug", sa.String(64), nullable=True))

    _backfill_usernames()
    op.alter_column("users", "username", existing_type=sa.String(32), nullable=False)

    for table, creator_column in _TABLES.items():
        _backfill_listing(table, creator_column)
        op.alter_column(table, "namespace", existing_type=sa.String(32), nullable=False)
        op.alter_column(table, "slug", existing_type=sa.String(64), nullable=False)
        op.create_index(f"ix_{table}_namespace", table, ["namespace"])

    op.drop_index("uq_agents_active_name", table_name="agents")
    op.create_index(
        "uq_agents_active_namespace_slug",
        "agents",
        ["namespace", "slug"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
        sqlite_where=sa.text("deleted_at IS NULL"),
    )

    for table in _COMPONENT_TABLES:
        op.drop_constraint(f"uq_{table}_name", table, type_="unique")
        op.create_unique_constraint(f"uq_{table}_namespace_slug", table, ["namespace", "slug"])


def downgrade() -> None:
    op.drop_index("uq_agents_active_namespace_slug", table_name="agents")
    _dedupe_names_for_downgrade("agents", active_only=True)
    op.create_index(
        "uq_agents_active_name",
        "agents",
        ["name"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
        sqlite_where=sa.text("deleted_at IS NULL"),
    )

    for table in _COMPONENT_TABLES:
        op.drop_constraint(f"uq_{table}_namespace_slug", table, type_="unique")
        _dedupe_names_for_downgrade(table)
        op.create_unique_constraint(f"uq_{table}_name", table, ["name"])

    for table in _TABLES:
        op.drop_index(f"ix_{table}_namespace", table_name=table)
        op.drop_column(table, "slug")
        op.drop_column(table, "namespace")

    op.alter_column("users", "username", existing_type=sa.String(32), nullable=True)
