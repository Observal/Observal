# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: Apache-2.0
"""DuckDB client: connection management, query execution, and timestamp helpers.

This module replaces the legacy ClickHouse HTTP client. Two deliberate
compatibility decisions keep the migration low-risk:

1. ``_query`` returns a :class:`QueryResult` shaped like the old
   ``httpx.Response`` (``status_code``, ``json() -> {"data": [...]}``,
   ``raise_for_status()``, ``text``) so existing callers keep working
   unchanged.

2. ``_translate_sql`` accepts legacy ClickHouse-isms that are mechanical to
   rewrite - ``{name:Type}`` placeholders, trailing ``FORMAT JSON`` and
   ``SETTINGS ...`` clauses - and converts them to DuckDB syntax. This is a
   safety net for call sites the manual port missed, not a license to write
   new ClickHouse-flavoured SQL.

Concurrency: DuckDB is an embedded, single-writer engine. All access goes
through one process-wide connection guarded by an RLock; coroutines run
queries via ``asyncio.to_thread`` so the event loop never blocks.
"""

import asyncio
import os
import re
import threading
import time
from datetime import UTC, date, datetime

from loguru import logger as optic

import duckdb
from config import settings

# Legacy ClickHouse placeholder: {name:Type} -> $name
_PLACEHOLDER_RE = re.compile(r"\{(\w+):[A-Za-z0-9_()'\s]+\}")
# Trailing ClickHouse clauses that have no DuckDB meaning.
_FORMAT_JSON_RE = re.compile(r"\s+FORMAT\s+JSON(EachRow)?\s*;?\s*$", re.IGNORECASE)
_SETTINGS_RE = re.compile(r"\s+SETTINGS\s+[\w\s=.,']+$", re.IGNORECASE)
# ClickHouse FINAL after a table name: merge-on-read dedup. DuckDB primary-key
# tables dedup at write time, so FINAL is always a no-op.
_FINAL_RE = re.compile(r"(\bFROM\s+\w+)\s+FINAL\b", re.IGNORECASE)
# Scalar rewrites: now64(3) -> naive-UTC now; toUnixTimestamp64Milli -> epoch_ms.
_NOW64_RE = re.compile(r"\bnow64\(\s*3?\s*\)", re.IGNORECASE)
_UNIX_TS_MS_RE = re.compile(r"\btoUnixTimestamp64Milli\(", re.IGNORECASE)
_TO_UINT64_RE = re.compile(r"\btoUInt64\(", re.IGNORECASE)
# ClickHouse count() == count(*)
_COUNT_EMPTY_RE = re.compile(r"\bcount\(\s*\)", re.IGNORECASE)
# INTERVAL $param UNIT -> ($param * INTERVAL '1 unit'); DuckDB intervals can't
# bind parameters directly. Applied after placeholder translation.
_INTERVAL_PARAM_RE = re.compile(
    r"INTERVAL\s+\$(\w+)\s+(DAY|MINUTE|HOUR|SECOND|WEEK|MONTH|YEAR)S?\b", re.IGNORECASE
)

_con: duckdb.DuckDBPyConnection | None = None
_lock = threading.RLock()


class AnalyticsQueryError(Exception):
    """Raised by QueryResult.raise_for_status() when a query failed."""


class QueryResult:
    """httpx.Response-shaped result for backwards compatibility.

    Successful queries carry ``status_code == 200`` and rows under
    ``json()["data"]`` as a list of dicts - identical to ClickHouse
    ``FORMAT JSON`` responses, except values are native Python types
    (datetime, int, float, str, None) instead of JSON primitives.
    """

    def __init__(
        self,
        columns: list[str] | None = None,
        rows: list[tuple] | None = None,
        *,
        status_code: int = 200,
        text: str = "",
    ):
        self._columns = columns or []
        self._rows = rows or []
        self.status_code = status_code
        self.text = text

    @staticmethod
    def _json_value(v):
        """Match ClickHouse FORMAT JSON value types: timestamps are strings
        ("YYYY-MM-DD HH:MM:SS.mmm"), dates are "YYYY-MM-DD"; everything else
        stays a native Python primitive."""
        if isinstance(v, datetime):
            return v.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        if isinstance(v, date):
            return v.strftime("%Y-%m-%d")
        return v

    def json(self) -> dict:
        return {
            "data": [
                {k: self._json_value(v) for k, v in zip(self._columns, row, strict=True)}
                for row in self._rows
            ]
        }

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise AnalyticsQueryError(f"DuckDB query failed ({self.status_code}): {self.text[:500]}")


def _get_con() -> duckdb.DuckDBPyConnection:
    """Process-wide DuckDB connection (created lazily)."""
    global _con
    with _lock:
        if _con is None:
            path = settings.DUCKDB_PATH
            if not settings.DUCKDB_READ_ONLY:
                parent = os.path.dirname(os.path.abspath(path))
                os.makedirs(parent, exist_ok=True)
            optic.debug("opening DuckDB database (path={}, read_only={})", path, settings.DUCKDB_READ_ONLY)
            _con = duckdb.connect(path, read_only=settings.DUCKDB_READ_ONLY)
            # All TIMESTAMP columns store naive UTC (legacy DateTime64(3,'UTC')
            # semantics). Pinning the session zone makes now()::TIMESTAMP
            # produce naive UTC as well.
            _con.execute("SET TimeZone = 'UTC'")
        return _con


def close_con() -> None:
    """Close the connection (used by tests and clean shutdown)."""
    global _con
    with _lock:
        if _con is not None:
            _con.close()
            _con = None


def _translate_sql(sql: str) -> str:
    """Convert legacy ClickHouse query syntax to DuckDB syntax."""
    sql = _SETTINGS_RE.sub("", sql.strip().rstrip(";"))
    sql = _FORMAT_JSON_RE.sub("", sql)
    sql = _FINAL_RE.sub(r"\1", sql)
    sql = _NOW64_RE.sub("now()::TIMESTAMP", sql)
    sql = _COUNT_EMPTY_RE.sub("count(*)", sql)
    sql = _UNIX_TS_MS_RE.sub("epoch_ms(", sql)
    # toUInt64(x) -> CAST(x AS UBIGINT); rare, only in version columns.
    while m := _TO_UINT64_RE.search(sql):
        depth, i = 1, m.end()
        while depth and i < len(sql):
            if sql[i] == "(":
                depth += 1
            elif sql[i] == ")":
                depth -= 1
            i += 1
        inner = sql[m.end() : i - 1]
        sql = sql[: m.start()] + f"({inner})::UBIGINT" + sql[i:]
    sql = _PLACEHOLDER_RE.sub(r"$\1", sql)
    # CAST guards legacy callers that stringify numeric params.
    sql = _INTERVAL_PARAM_RE.sub(
        lambda m: f"(CAST(${m.group(1)} AS INTEGER) * INTERVAL '1 {m.group(2).lower()}')", sql
    )
    return sql


def _translate_params(params: dict | None) -> dict:
    """Strip the legacy ``param_`` prefix ClickHouse required."""
    if not params:
        return {}
    return {k.removeprefix("param_"): v for k, v in params.items()}


def _execute(sql: str, params: dict | None = None) -> QueryResult:
    bound_sql = _translate_sql(sql)
    bound_params = _translate_params(params)
    # DuckDB rejects named parameters that don't appear in the statement;
    # legacy callers routinely pass unused params (e.g. lookback windows for
    # stub queries). Drop anything unreferenced after translation.
    bound_params = {
        k: v for k, v in bound_params.items() if re.search(rf"\${re.escape(k)}\b", bound_sql)
    }
    with _lock:
        con = _get_con()
        cur = con.execute(bound_sql, bound_params) if bound_params else con.execute(bound_sql)
        if cur.description is None:
            return QueryResult()
        columns = [d[0] for d in cur.description]
        return QueryResult(columns, cur.fetchall())


async def _query(sql: str, params: dict | None = None, *, data: str | None = None) -> QueryResult:
    """Execute a DuckDB query. Signature and result shape match the legacy
    ClickHouse HTTP client.

    Args:
        sql: SQL statement. DuckDB-native ``$name`` placeholders preferred;
            legacy ``{name:Type}`` placeholders are auto-translated.
        params: Parameter dict; the legacy ``param_`` prefix is stripped.
        data: Newline-delimited JSON objects for legacy
            ``INSERT ... FORMAT JSONEachRow`` statements.
    """
    _t0 = time.perf_counter()
    try:
        if data is not None:
            result = await asyncio.to_thread(_insert_json_each_row, sql, data)
        else:
            result = await asyncio.to_thread(_execute, sql, params)
        _elapsed = (time.perf_counter() - _t0) * 1000
        if result.status_code >= 400:
            optic.warning(
                "DuckDB query failed in {:.0f}ms - error preview: {}", _elapsed, result.text[:200]
            )
        else:
            optic.trace("DuckDB query OK ({:.0f}ms)", _elapsed)
        return result
    except Exception as e:
        _elapsed = (time.perf_counter() - _t0) * 1000
        optic.error("DuckDB query raised after {:.0f}ms: {} - SQL starts with: {}", _elapsed, e, sql[:80])
        return QueryResult(status_code=500, text=str(e))


def _insert_json_each_row(sql: str, data: str) -> QueryResult:
    """Compatibility path for legacy ``INSERT ... FORMAT JSONEachRow`` calls.

    Parses the JSON rows and executes a parameterized batch insert. New code
    should use the helpers in services.duckdb.insert instead.
    """
    import orjson

    import services.duckdb.insert as _insert

    rows = [orjson.loads(line) for line in data.splitlines() if line.strip()]
    if not rows:
        return QueryResult()
    stmt = _translate_sql(sql)
    # stmt looks like: INSERT [OR REPLACE] INTO tbl [(col, ...)] [SETTINGS ...]
    m = re.match(r"(?i)^\s*INSERT\s+(OR\s+REPLACE\s+)?INTO\s+(\w+)\s*(?:\(([^)]*)\))?", stmt)
    if not m:
        return QueryResult(status_code=400, text=f"unsupported INSERT statement: {sql[:120]}")
    or_replace = bool(m.group(1))
    table = m.group(2)
    col_list = [c.strip() for c in m.group(3).split(",")] if m.group(3) else None
    _insert.insert_rows(table, rows, columns=col_list, or_replace=or_replace)
    return QueryResult()


def _now_ms() -> str:
    """Current UTC timestamp as ISO string with millisecond precision."""
    return datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]


_TS_SENTINEL_CUTOFF = datetime(2099, 1, 1, tzinfo=UTC)


def _normalize_ts(value: str | None) -> str | None:
    """Normalize a timestamp string for DuckDB TIMESTAMP (naive UTC).

    Converts ISO 8601 ``T``/``Z`` separators to the ``YYYY-MM-DD HH:MM:SS.mmm``
    form and clamps far-future sentinel timestamps (e.g. Kiro placeholders)
    to now, preserving legacy behaviour.
    """
    if value is None:
        return None
    v = value.replace("T", " ").rstrip("Z")
    if "." not in v:
        v += ".000"
    try:
        parsed = datetime.fromisoformat(v.replace(" ", "T") + "+00:00")
        if parsed >= _TS_SENTINEL_CUTOFF:
            optic.trace("clamping far-future timestamp {} to now", value)
            v = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S.%f")[:23]
    except ValueError:
        optic.trace("could not parse timestamp '{}', passing through as-is", value)
    return v


async def duckdb_health() -> bool:
    """Check DuckDB connectivity. Returns True if healthy."""
    _t0 = time.perf_counter()
    try:
        resp = await _query("SELECT 1")
        healthy = resp.status_code == 200
        _elapsed = (time.perf_counter() - _t0) * 1000
        if healthy:
            optic.debug("DuckDB is reachable ({:.0f}ms)", _elapsed)
        return healthy
    except Exception as e:
        _elapsed = (time.perf_counter() - _t0) * 1000
        optic.error("DuckDB health check failed after {:.0f}ms: {}", _elapsed, e)
        return False


async def _invalidate_cache():
    """Best-effort cache invalidation after analytics writes."""
    try:
        from services.cache import invalidate_all

        await invalidate_all()
    except Exception as e:
        optic.trace("cache invalidation skipped (best-effort): {}", e)
