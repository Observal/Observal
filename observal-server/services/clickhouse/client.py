# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only
"""ClickHouse HTTP client: connection pool, query execution, and timestamp helpers."""

from datetime import UTC, datetime
from urllib.parse import urlparse

import httpx
import structlog
from loguru import logger as optic
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from config import settings

logger = structlog.get_logger(__name__)

_parsed = urlparse(settings.CLICKHOUSE_URL.replace("clickhouse://", "http://"))
CLICKHOUSE_HTTP = f"http://{_parsed.hostname}:{_parsed.port or 8123}"
CLICKHOUSE_DB = _parsed.path.strip("/") or "default"
CLICKHOUSE_USER = _parsed.username or "default"
CLICKHOUSE_PASSWORD = _parsed.password or ""

_client: httpx.AsyncClient | None = None


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(
            timeout=settings.CLICKHOUSE_TIMEOUT,
            limits=httpx.Limits(
                max_connections=settings.CLICKHOUSE_MAX_CONNECTIONS,
                max_keepalive_connections=settings.CLICKHOUSE_MAX_KEEPALIVE,
            ),
        )
    return _client


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=0.5, min=0.5, max=5),
    retry=retry_if_exception_type((httpx.ConnectError, httpx.ConnectTimeout)),
    reraise=True,
)
async def _query(sql: str, params: dict | None = None, *, data: str | None = None):
    """Execute a ClickHouse query via HTTP.

    Args:
        sql: The SQL statement.  Use ``{name:Type}`` placeholders for
            parameterized queries.
        params: Parameter dict - keys **must** use the ``param_`` prefix
            (e.g. ``{"param_pid": "default"}``).
        data: Optional body content appended after the SQL, separated by a
            newline.  Used for ``INSERT ... FORMAT JSONEachRow`` where each
            line in *data* is a JSON object.
    """
    from services.clickhouse._settings import DEFAULT_QUERY_SETTINGS, _resource_overrides

    client = _get_client()
    query_params: dict[str, str] = {
        "database": CLICKHOUSE_DB,
        "user": CLICKHOUSE_USER,
        "password": CLICKHOUSE_PASSWORD,
    }
    query_params.update(DEFAULT_QUERY_SETTINGS)
    if _resource_overrides:
        query_params.update(_resource_overrides)
    if params:
        query_params.update(params)
    body = f"{sql}\n{data}" if data else sql
    return await client.post(CLICKHOUSE_HTTP, content=body, params=query_params)


async def clickhouse_health() -> bool:
    """Check ClickHouse connectivity. Returns True if healthy."""
    optic.debug("clickhouse_health check")
    try:
        resp = await _query("SELECT 1")
        return resp.status_code == 200
    except Exception:
        return False


def _now_ms() -> str:
    """Current UTC timestamp as ISO string with millisecond precision."""
    return datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]


_TS_SENTINEL_CUTOFF = datetime(2099, 1, 1, tzinfo=UTC)


def _normalize_ts(value: str | None) -> str | None:
    """Normalize a timestamp string for ClickHouse DateTime64 compatibility.

    ClickHouse JSONEachRow cannot parse ISO 8601 ``T``/``Z`` separators,
    so we convert ``2026-04-21T07:35:00Z`` -> ``2026-04-21 07:35:00.000``.

    Also clamps future sentinel timestamps (e.g. Kiro emits far-future
    placeholders) to now so session_stats_agg stores a real last_event_time.
    """
    if value is None:
        return None
    v = value.replace("T", " ").rstrip("Z")
    if "." not in v:
        v += ".000"
    try:
        parsed = datetime.fromisoformat(v.replace(" ", "T") + "+00:00")
        if parsed >= _TS_SENTINEL_CUTOFF:
            v = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S.%f")[:23]
    except ValueError:
        pass
    return v


async def _invalidate_cache():
    """Best-effort cache invalidation after ClickHouse writes."""
    try:
        from services.cache import invalidate_all

        await invalidate_all()
    except Exception:
        pass
