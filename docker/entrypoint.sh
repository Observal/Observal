#!/bin/bash
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

echo "Stamping alembic to head (models are canonical)..."
/app/.venv/bin/python -m alembic stamp head

echo "Ensuring ClickHouse database exists..."
# Parse credentials from CLICKHOUSE_URL using Python to handle special chars
eval "$(/app/.venv/bin/python -c "
from urllib.parse import urlparse, unquote
import os
url = urlparse(os.environ.get('CLICKHOUSE_URL', 'clickhouse://default:clickhouse@observal-clickhouse:8123/observal'))
print(f'CH_HOST={url.hostname}:{url.port or 8123}')
print(f'CH_USER={unquote(url.username or \"default\")}')
print(f'CH_PASS={unquote(url.password or \"clickhouse\")}')
print(f'CH_DB={url.path.lstrip(\"/\") or \"observal\"}')
")"
CH_PROTO_HOST="http://${CH_HOST}"

CH_CREATE_RETRIES=15
CH_CREATE_COUNT=0
while [ $CH_CREATE_COUNT -lt $CH_CREATE_RETRIES ]; do
  HTTP_CODE=$(/app/.venv/bin/python -c "
import urllib.request, base64, sys
url = '${CH_PROTO_HOST}/'
auth = base64.b64encode('${CH_USER}:${CH_PASS}'.encode()).decode()
req = urllib.request.Request(url, data=b'CREATE DATABASE IF NOT EXISTS ${CH_DB}', headers={'Authorization': 'Basic ' + auth})
try:
    urllib.request.urlopen(req, timeout=5)
    print('ok')
except Exception:
    print('fail')
" 2>/dev/null)
  if [ "$HTTP_CODE" = "ok" ]; then
    echo "ClickHouse database '${CH_DB}' ready"
    break
  fi
  CH_CREATE_COUNT=$((CH_CREATE_COUNT + 1))
  if [ $CH_CREATE_COUNT -ge $CH_CREATE_RETRIES ]; then
    echo "ClickHouse not reachable after $CH_CREATE_RETRIES attempts, aborting."
    exit 1
  fi
  WAIT=$(( 2 ** CH_CREATE_COUNT > 30 ? 30 : 2 ** CH_CREATE_COUNT ))
  echo "Waiting for ClickHouse to accept connections (attempt $CH_CREATE_COUNT/$CH_CREATE_RETRIES, retry in ${WAIT}s)..."
  sleep "$WAIT"
done

echo "Initializing ClickHouse tables..."
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
      WAIT_TIME=$(( 2 ** RETRY_COUNT > 30 ? 30 : 2 ** RETRY_COUNT ))
      echo "ClickHouse initialization failed. Retrying in ${WAIT_TIME}s (attempt $RETRY_COUNT/$MAX_RETRIES)..."
      sleep "$WAIT_TIME"
    else
      echo "ClickHouse initialization failed after $MAX_RETRIES attempts"
      exit 1
    fi
  fi
done

echo "Initialization complete."
