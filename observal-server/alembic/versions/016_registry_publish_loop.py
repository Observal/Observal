# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""Add canonical user namespaces to registry listings.

Revision ID: 016_registry_publish_loop
Revises: 015_sandbox_runtime_config
"""

import re
from collections import defaultdict

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


def _migration_slug(name: str) -> str:
    slug = re.sub(r"[^a-z0-9_-]+", "-", name.strip().lower()).strip("-_")
    return (slug or "item")[:64].rstrip("-_")


def _next_slug(base: str, used: set[str], *, reserved: bool = False) -> str:
    number = 1 if reserved else None
    while True:
        suffix = f"-{number}" if number is not None else ""
        candidate = f"{base[: 64 - len(suffix)].rstrip('-_')}{suffix}"
        if candidate not in used:
            used.add(candidate)
            return candidate
        number = 1 if number is None else number + 1


def _listing_identities(table: str, rows):
    used_by_namespace: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        namespace = row["username"]
        if namespace is None:
            raise RuntimeError(f"Cannot backfill {table} namespace: orphaned listing {row['id']}")
        base = _migration_slug(row["name"])
        slug = _next_slug(base, used_by_namespace[namespace], reserved=base in _RESERVED_SLUGS)
        yield row["id"], namespace, slug


def _backfill_listing(table: str, creator_column: str) -> None:
    listing = sa.table(
        table,
        sa.column("id"),
        sa.column("name"),
        sa.column("created_at"),
        sa.column(creator_column),
        sa.column("namespace"),
        sa.column("slug"),
    )
    users = sa.table("users", sa.column("id"), sa.column("username"))
    rows = (
        op.get_bind()
        .execute(
            sa.select(
                listing.c.id,
                listing.c.name,
                users.c.username.label("username"),
            )
            .select_from(listing.outerjoin(users, listing.c[creator_column] == users.c.id))
            .order_by(listing.c.created_at, listing.c.id)
        )
        .mappings()
        .all()
    )

    for listing_id, namespace, slug in _listing_identities(table, rows):
        op.execute(listing.update().where(listing.c.id == listing_id).values(namespace=namespace, slug=slug))


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
