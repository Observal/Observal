#!/bin/sh
set -e

echo "Ensuring base schema exists..."
/app/.venv/bin/python -c "
import asyncio
from database import engine
from models import Base

async def init():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await engine.dispose()

asyncio.run(init())
"

echo "Running database migrations..."
/app/.venv/bin/python -m alembic upgrade head

echo "Initializing ClickHouse tables..."
/app/.venv/bin/python -c "
import asyncio
from services.clickhouse import init_clickhouse

asyncio.run(init_clickhouse())
"

echo "Initialization complete."
