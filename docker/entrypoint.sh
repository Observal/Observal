#!/bin/bash
# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-FileCopyrightText: 2026 Lokesh Selvam <lokeshselvam7025@gmail.com>
# SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
# SPDX-FileCopyrightText: 2026 Swathi Saravanan <ss4522@cornell.edu>
# SPDX-License-Identifier: Apache-2.0

set -e

echo "Ensuring base schema exists..."
/app/.venv/bin/python -c "
import asyncio
from sqlalchemy import text
from database import engine
from models import Base

async def init():
    async with engine.begin() as conn:
        await conn.execute(text('CREATE EXTENSION IF NOT EXISTS pg_trgm;'))
        await conn.run_sync(Base.metadata.create_all)
    await engine.dispose()

asyncio.run(init())
"

echo "Running database migrations..."
if ! /app/.venv/bin/python -m alembic upgrade head; then
    # Only stamp on a genuinely fresh database: one with no recorded alembic
    # revision. A failure on a DB that already has an alembic_version row means
    # a real migration problem (e.g. DuplicateTableError from a partial run),
    # and stamping HEAD would silently skip the missing migrations.
    DB_STATE=$(/app/.venv/bin/python -c "
import asyncio
from sqlalchemy import text
from database import engine

async def check():
    async with engine.connect() as conn:
        has_table = await conn.scalar(
            text(\"SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'alembic_version')\")
        )
        if not has_table:
            return 'fresh'
        rev = await conn.scalar(text('SELECT version_num FROM alembic_version LIMIT 1'))
        return 'fresh' if not rev else 'existing'

try:
    print(asyncio.run(check()))
finally:
    asyncio.run(engine.dispose())
")
    if [ "$DB_STATE" = "fresh" ]; then
        echo "Fresh database detected: stamping current schema version..."
        /app/.venv/bin/python -m alembic stamp head
    else
        echo "ERROR: alembic upgrade failed on an existing database (revision present)."
        echo "Refusing to stamp HEAD; resolve the failing migration manually."
        exit 1
    fi
fi

echo "Running ClickHouse migrations..."
/app/.venv/bin/python -m services.clickhouse.migrations

echo "Initialization complete."
