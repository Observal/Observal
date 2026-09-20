# SPDX-FileCopyrightText: 2026 Srihari <sriharilegend23@gmail.com>
# SPDX-FileCopyrightText: 2026 Vishnu Muthiah <vishnu.muthiah04@gmail.com>
# SPDX-License-Identifier: Apache-2.0
"""HTTP client for the DuckDB analytics service.

The response contract intentionally mirrors the old ClickHouse HTTP client
(``{"data": [...]}``) so call sites swap dialects, not plumbing.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime
from urllib.parse import urlparse

import httpx
from loguru import logger as optic
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from config import settings

_parsed = urlparse(settings.DUCKDB_ANALYTICS_URL.replace("duckdb://", "http://"))
ANALYTICS_HTTP = f"http://{_parsed.hostname}:{_parsed.port or 8484}"
ANALYTICS_TOKEN = settings.DUCKDB_ANALYTICS_TOKEN

_client: httpx.AsyncClient | None = None


def _headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {ANALYTICS_TOKEN}"} if ANALYTICS_TOKEN else {}


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        optic.debug(
            "creating analytics HTTP client (host={}, timeout={}s, pool={})",
            _parsed.hostname,
            settings.DUCKDB_ANALYTICS_TIMEOUT,
            settings.DUCKDB_ANALYTICS_MAX_CONNECTIONS,
        )
        _client = httpx.AsyncClient(
            timeout=settings.DUCKDB_ANALYTICS_TIMEOUT,
            limits=httpx.Limits(
                max_connections=settings.DUCKDB_ANALYTICS_MAX_CONNECTIONS,
                max_keepalive_connections=settings.DUCKDB_ANALYTICS_MAX_CONNECTIONS,
            ),
        )
    return _client


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=0.5, min=0.5, max=5),
    retry=retry_if_exception_type((httpx.ConnectError, httpx.ConnectTimeout)),
    reraise=True,
)
async def _query(sql: str, params: dict | list | None = None) -> httpx.Response:
    """Run a read query against the analytics service.

    Args:
        sql: SQL with ``$name`` placeholders for named parameters.
        params: Parameter dict (``{"pid": "default"}``) or positional list.

    Returns the raw HTTP response; ``.json()["data"]`` holds the rows.
    """
    _t0 = time.perf_counter()
    client = _get_client()
    optic.trace("executing analytics query (sql_len={}, has_params={})", len(sql), params is not None)
    try:
        resp = await client.post(ANALYTICS_HTTP + "/query", json={"sql": sql, "params": params}, headers=_headers())
        _elapsed = (time.perf_counter() - _t0) * 1000
        if resp.status_code >= 400:
            optic.warning(
                "analytics query returned HTTP {} in {:.0f}ms - body preview: {}",
                resp.status_code,
                _elapsed,
                resp.text[:200],
            )
        else:
            optic.trace("analytics query OK (status={}, {:.0f}ms)", resp.status_code, _elapsed)
        return resp
    except Exception as e:
        _elapsed = (time.perf_counter() - _t0) * 1000
        optic.error("analytics query failed after {:.0f}ms: {} - SQL starts with: {}", _elapsed, e, sql[:80])
        raise


async def _execute(sql: str, params: dict | list | None = None) -> int:
    """Run a mutation against the analytics service; returns affected rows."""
    client = _get_client()
    resp = await client.post(ANALYTICS_HTTP + "/execute", json={"sql": sql, "params": params}, headers=_headers())
    resp.raise_for_status()
    return int(resp.json().get("row_count") or 0)


async def _insert(table: str, rows: list[dict]) -> int:
    """Bulk-insert rows into a whitelisted analytics table."""
    if not rows:
        return 0
    client = _get_client()
    resp = await client.post(ANALYTICS_HTTP + "/insert", json={"table": table, "rows": rows}, headers=_headers())
    resp.raise_for_status()
    return int(resp.json().get("row_count") or 0)


async def analytics_health(*, authenticated: bool = False) -> bool:
    """Check analytics connectivity and, optionally, authenticated access."""
    _t0 = time.perf_counter()
    try:
        endpoint = "/version" if authenticated else "/health"
        resp = await _get_client().get(ANALYTICS_HTTP + endpoint, headers=_headers())
        body = resp.json() if resp.status_code == 200 else {}
        healthy = resp.status_code == 200 and (authenticated or body.get("status") == "ok")
        _elapsed = (time.perf_counter() - _t0) * 1000
        if healthy:
            optic.debug(
                "DuckDB analytics is reachable{} ({:.0f}ms)", " with authentication" if authenticated else "", _elapsed
            )
        else:
            optic.warning("DuckDB analytics health check returned {} ({:.0f}ms)", resp.status_code, _elapsed)
        return healthy
    except Exception as e:
        _elapsed = (time.perf_counter() - _t0) * 1000
        optic.error("DuckDB analytics unreachable after {:.0f}ms: {}", _elapsed, e)
        return False


async def _refresh_session_summary(project_id: str, user_id: str, harness: str, session_id: str) -> None:
    """Atomically recompute one summary inside the analytics writer."""
    resp = await _get_client().post(
        ANALYTICS_HTTP + "/refresh_session_summary",
        json={"project_id": project_id, "user_id": user_id, "harness": harness, "session_id": session_id},
        headers=_headers(),
    )
    resp.raise_for_status()


async def _checkpoint() -> None:
    """Force a DuckDB checkpoint (WAL flush)."""
    resp = await _get_client().post(ANALYTICS_HTTP + "/admin/checkpoint", headers=_headers())
    resp.raise_for_status()


async def _apply_pragmas(pragmas: dict[str, str]) -> None:
    """Push resource-tuning pragmas to the analytics service."""
    if not pragmas:
        return
    resp = await _get_client().post(ANALYTICS_HTTP + "/admin/pragmas", json={"pragmas": pragmas}, headers=_headers())
    resp.raise_for_status()


def _now_ms() -> str:
    """Current UTC timestamp as ISO string with millisecond precision."""
    return datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]


_TS_SENTINEL_CUTOFF = datetime(2099, 1, 1, tzinfo=UTC)


def _normalize_ts(value: str | None) -> str | None:
    """Normalize a timestamp string for storage.

    Accepts ISO 8601 ``T``/``Z`` separators and clamps future sentinel
    timestamps (e.g. Kiro emits far-future placeholders) to now.
    """
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(value.strip())
        parsed = parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)
        if parsed >= _TS_SENTINEL_CUTOFF:
            optic.trace("clamping far-future timestamp {} to now", value)
            parsed = datetime.now(UTC)
        return parsed.strftime("%Y-%m-%d %H:%M:%S.%f")[:23]
    except ValueError:
        optic.trace("could not parse timestamp '{}', passing through as-is", value)
        return value


async def _invalidate_cache():
    """Best-effort cache invalidation after analytics writes."""
    try:
        from services.cache import invalidate_all

        await invalidate_all()
    except Exception as e:
        optic.trace("cache invalidation skipped (best-effort): {}", e)
