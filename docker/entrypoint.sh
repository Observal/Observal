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
/app/.venv/bin/python -m alembic upgrade head || {
    echo "Fresh database detected: stamping current schema version..."
    /app/.venv/bin/python -m alembic stamp head
}

echo "Running ClickHouse migrations..."
/app/.venv/bin/python -m services.clickhouse.migrations

echo "Initialization complete."
