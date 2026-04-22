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

echo "Ensuring ClickHouse database exists..."
# Parse credentials from CLICKHOUSE_URL (clickhouse://user:pass@host:port/db)
CH_URL="${CLICKHOUSE_URL:-clickhouse://default:clickhouse@observal-clickhouse:8123/observal}"
CH_HOST=$(echo "$CH_URL" | sed 's|clickhouse://[^@]*@||' | sed 's|/.*||')
CH_USER=$(echo "$CH_URL" | sed 's|clickhouse://||' | sed 's|:.*||')
CH_PASS=$(echo "$CH_URL" | sed 's|clickhouse://[^:]*:||' | sed 's|@.*||')
CH_DB=$(echo "$CH_URL" | sed 's|.*/||')
CH_PROTO_HOST="http://${CH_HOST}"

CH_CREATE_RETRIES=15
CH_CREATE_COUNT=0
while [ $CH_CREATE_COUNT -lt $CH_CREATE_RETRIES ]; do
  HTTP_CODE=$(wget -q -O- "${CH_PROTO_HOST}/?user=${CH_USER}&password=${CH_PASS}" \
    --post-data="CREATE DATABASE IF NOT EXISTS ${CH_DB}" 2>/dev/null && echo "ok" || echo "fail")
  if [ "$HTTP_CODE" = "ok" ]; then
    echo "ClickHouse database '${CH_DB}' ready"
    break
  fi
  CH_CREATE_COUNT=$((CH_CREATE_COUNT + 1))
  WAIT=$((2 ** CH_CREATE_COUNT > 30 ? 30 : 2 ** CH_CREATE_COUNT))
  echo "Waiting for ClickHouse to accept connections (attempt $CH_CREATE_COUNT/$CH_CREATE_RETRIES, retry in ${WAIT}s)..."
  sleep "$WAIT"
  if [ $CH_CREATE_COUNT -ge $CH_CREATE_RETRIES ]; then
    echo "ClickHouse not reachable after $CH_CREATE_RETRIES attempts, aborting."
    exit 1
  fi
done

echo "Initializing ClickHouse tables..."
# Retry logic for ClickHouse initialization
MAX_RETRIES=10
RETRY_COUNT=0
while [ $RETRY_COUNT -lt $MAX_RETRIES ]; do
  if /app/.venv/bin/python -c "
import asyncio
from services.clickhouse import init_clickhouse

asyncio.run(init_clickhouse())
"; then
    echo "ClickHouse initialization successful"
    break
  else
    RETRY_COUNT=$((RETRY_COUNT + 1))
    if [ $RETRY_COUNT -lt $MAX_RETRIES ]; then
      WAIT_TIME=$((2 ** RETRY_COUNT))
      echo "ClickHouse initialization failed. Retrying in ${WAIT_TIME}s (attempt $RETRY_COUNT/$MAX_RETRIES)..."
      sleep $WAIT_TIME
    else
      echo "ClickHouse initialization failed after $MAX_RETRIES attempts"
      exit 1
    fi
  fi
done

echo "Initialization complete."
