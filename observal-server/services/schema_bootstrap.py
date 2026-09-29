# SPDX-FileCopyrightText: 2026 Observal Contributors
# SPDX-License-Identifier: Apache-2.0

"""Inspect PostgreSQL before initialization and install fresh-only schema objects.

An unversioned database containing tables must never be stamped as current. On
an empty database, create the current model and the objects that only exist in
historical migrations before stamping head. Versioned databases use Alembic.
"""

from __future__ import annotations

import asyncio
import sys
from typing import TYPE_CHECKING

from sqlalchemy import text

from database import engine
from models import Base

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncConnection


async def schema_state(connection: AsyncConnection) -> str:
    """Return fresh, existing, or unversioned without changing the database."""
    has_version_table = await connection.scalar(
        text(
            "SELECT EXISTS (SELECT 1 FROM pg_catalog.pg_tables "
            "WHERE schemaname = current_schema() AND tablename = 'alembic_version')"
        )
    )
    if has_version_table:
        version = await connection.scalar(text("SELECT version_num FROM alembic_version LIMIT 1"))
        return "existing" if version else "unversioned"

    has_tables = await connection.scalar(
        text("SELECT EXISTS (SELECT 1 FROM pg_catalog.pg_tables WHERE schemaname = current_schema())")
    )
    return "unversioned" if has_tables else "fresh"


async def bootstrap_fresh_schema_objects(connection: AsyncConnection) -> None:
    """Create current migration-only objects after the model's tables exist."""
    await connection.execute(
        text(
            "CREATE SEQUENCE IF NOT EXISTS projection_generation_seq "
            "AS bigint MINVALUE 1 MAXVALUE 9223372036854775807 NO CYCLE CACHE 1"
        )
    )
    # Migration 027 creates this index, but DiscoveryEntry's model does not.
    # Otherwise a create_all + stamp head install silently loses search indexing.
    await connection.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_discovery_entries_search_trgm "
            "ON discovery_entries USING gin (search_document gin_trgm_ops)"
        )
    )
    await connection.execute(
        text("""
            CREATE OR REPLACE FUNCTION insight_report_cleanup_on_listing_delete() RETURNS trigger AS $$
            BEGIN
                DELETE FROM insight_reports
                 WHERE subject_type = 'component' AND component_type = TG_ARGV[0] AND component_id = OLD.id;
                RETURN OLD;
            END;
            $$ LANGUAGE plpgsql
        """)
    )
    for kind in ("mcp", "skill", "hook"):
        # Names are fixed code constants, not supplied by users.
        await connection.execute(
            text(f"""
                DO $$ BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM pg_trigger
                        WHERE tgrelid = '{kind}_listings'::regclass
                          AND tgname = 'trg_{kind}_insight_report_cleanup'
                    ) THEN
                        CREATE TRIGGER trg_{kind}_insight_report_cleanup
                        AFTER DELETE ON {kind}_listings FOR EACH ROW
                        EXECUTE FUNCTION insight_report_cleanup_on_listing_delete('{kind}');
                    END IF;
                END $$
            """)
        )


async def initialize_fresh_schema(connection: AsyncConnection) -> None:
    """Fail closed if another process or a previous attempt created any tables."""
    if await schema_state(connection) != "fresh":
        raise RuntimeError("Refusing to initialize or stamp a nonempty/unversioned database")
    await connection.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
    await connection.run_sync(Base.metadata.create_all)
    await bootstrap_fresh_schema_objects(connection)


async def _main(action: str) -> None:
    try:
        if action == "state":
            async with engine.connect() as connection:
                print(await schema_state(connection))
        else:
            async with engine.begin() as connection:
                await initialize_fresh_schema(connection)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in {"state", "init"}:
        raise SystemExit("usage: python -m services.schema_bootstrap {state|init}")
    asyncio.run(_main(sys.argv[1]))
