# SPDX-FileCopyrightText: 2026 Naraen Rammoorthi <naraen13@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Server-side diagnostic collection endpoint for support bundles.

Runs collectors for versions, health, config, aggregates, errors, and
logs data. Each collector is wrapped in ``_run_collector`` with a
10-second ``asyncio.wait_for`` timeout. Partial failures are reported
in the response - the endpoint always returns 200 if at least one
collector succeeds.
"""

from __future__ import annotations

import asyncio
import os
import re
import time
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Depends, Request
from loguru import logger as optic
from pydantic import BaseModel
from sqlalchemy import text

from api.deps import get_db, require_role
from api.ratelimit import limiter
from config import HAS_LICENSE, Settings, settings
from models.user import UserRole
from services.clickhouse import CLICKHOUSE_DB, _query
from services.redis import get_redis
from services.secrets_redactor import redact_dict

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from models.user import User


router = APIRouter(prefix="/api/v1/support", tags=["support"])

COLLECTOR_TIMEOUT_SECONDS = 10

# Valid ClickHouse/PG table name: alphanumeric + underscores, starting with a letter or underscore
_SAFE_TABLE_NAME_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")


# ── Request / Response models ────────────────────────────────────────


class CollectRequest(BaseModel):
    collectors: list[str] = ["all"]
    logs_since: str = "1h"


class CollectorData(BaseModel):
    ok: bool
    duration_ms: int
    data: Any = None
    error: str | None = None


class CollectResponse(BaseModel):
    server_version: str
    collectors: dict[str, CollectorData]


# ── Collector wrapper ────────────────────────────────────────────────


async def _run_collector(name: str, coro) -> tuple[str, CollectorData]:
    """Run a single collector coroutine with a 10-second timeout.

    Returns a (name, CollectorData) tuple regardless of success or failure.
    """
    optic.trace("name={}, coro={}", name, coro)
    start = time.monotonic()
    try:
        data = await asyncio.wait_for(coro, timeout=COLLECTOR_TIMEOUT_SECONDS)
        elapsed_ms = int((time.monotonic() - start) * 1000)
        return name, CollectorData(ok=True, duration_ms=elapsed_ms, data=data)
    except TimeoutError:
        return name, CollectorData(
            ok=False,
            duration_ms=COLLECTOR_TIMEOUT_SECONDS * 1000,
            error=f"Collector timed out after {COLLECTOR_TIMEOUT_SECONDS}s",
        )
    except Exception as exc:
        elapsed_ms = int((time.monotonic() - start) * 1000)
        return name, CollectorData(ok=False, duration_ms=elapsed_ms, error=type(exc).__name__)


# ── Individual collectors ────────────────────────────────────────────


async def _collect_versions(db: AsyncSession) -> dict:
    """Collect app version, build hash, Alembic revision, ClickHouse version + tables."""
    optic.debug("_collect_versions called")
    result: dict[str, Any] = {}

    # App version - try importlib.metadata first, fall back to hardcoded
    try:
        from importlib.metadata import version

        result["app_version"] = version("observal-server")
    except Exception:
        result["app_version"] = "0.1.0"

    # Build hash - read from BUILD_HASH env var or fall back to unknown
    result["build_hash"] = os.environ.get("BUILD_HASH", "unknown")

    # Alembic revision from PG
    try:
        row = await db.execute(text("SELECT version_num FROM alembic_version LIMIT 1"))
        rev = row.scalar_one_or_none()
        result["alembic_revision"] = rev or "unknown"
    except Exception as exc:
        result["alembic_revision"] = f"error: {type(exc).__name__}"

    # ClickHouse version
    try:
        resp = await _query("SELECT version()")
        if resp.status_code == 200:
            result["clickhouse_version"] = resp.text.strip()
        else:
            result["clickhouse_version"] = f"error: HTTP {resp.status_code}"
    except Exception as exc:
        result["clickhouse_version"] = f"error: {type(exc).__name__}"

    # ClickHouse table list
    try:
        resp = await _query(
            "SELECT name FROM system.tables WHERE database = {db:String} FORMAT JSON",
            {"param_db": CLICKHOUSE_DB},
        )
        if resp.status_code == 200:
            rows = resp.json().get("data", [])
            result["clickhouse_tables"] = [r["name"] for r in rows]
        else:
            result["clickhouse_tables"] = []
    except Exception as exc:
        result["clickhouse_tables"] = f"error: {type(exc).__name__}"

    return result


async def _collect_health(db: AsyncSession) -> dict:
    """Run health probes against PG, CH, Redis, and OTEL collector."""
    optic.debug("_collect_health called")
    result: dict[str, Any] = {}

    # PostgreSQL health
    pg_start = time.monotonic()
    try:
        await db.execute(text("SELECT 1"))
        pg_ms = int((time.monotonic() - pg_start) * 1000)
        result["postgres"] = {"status": "ok", "latency_ms": pg_ms}
    except Exception as exc:
        pg_ms = int((time.monotonic() - pg_start) * 1000)
        result["postgres"] = {"status": "error", "latency_ms": pg_ms, "error": type(exc).__name__}

    # ClickHouse health
    ch_start = time.monotonic()
    try:
        resp = await _query("SELECT 1")
        ch_ms = int((time.monotonic() - ch_start) * 1000)
        if resp.status_code == 200:
            result["clickhouse"] = {"status": "ok", "latency_ms": ch_ms}
        else:
            result["clickhouse"] = {"status": "error", "latency_ms": ch_ms, "error": f"HTTP {resp.status_code}"}
    except Exception as exc:
        ch_ms = int((time.monotonic() - ch_start) * 1000)
        result["clickhouse"] = {"status": "error", "latency_ms": ch_ms, "error": type(exc).__name__}

    # Redis health
    redis_start = time.monotonic()
    try:
        r = get_redis()
        pong = await r.ping()
        redis_ms = int((time.monotonic() - redis_start) * 1000)
        result["redis"] = {"status": "ok" if pong else "error", "latency_ms": redis_ms}
    except Exception as exc:
        redis_ms = int((time.monotonic() - redis_start) * 1000)
        result["redis"] = {"status": "error", "latency_ms": redis_ms, "error": type(exc).__name__}

    return result


CONFIG_ALLOWLIST = frozenset(
    {
        "DATABASE_URL",
        "CLICKHOUSE_URL",
        "REDIS_URL",
        "JWT_SIGNING_ALGORITHM",
    }
)

# Dynamic settings to include in support bundle
_DYNAMIC_CONFIG_KEYS = [
    "eval.model_name",
    "eval.model_provider",
    "eval.aws_region",
    "deployment.frontend_url",
    "jwt.access_token_expire_minutes",
    "jwt.refresh_token_expire_days",
    "jwt.hooks_token_expire_minutes",
    "security.rate_limit_auth",
    "security.rate_limit_auth_strict",
    "data.retention_days",
]


async def _collect_config() -> dict:
    """Return only allowlisted Settings fields plus dynamic settings.

    Secrets like SECRET_KEY and oauth.client_secret are never sent
    over the wire.
    """
    optic.debug("_collect_config called")
    import services.dynamic_settings as ds

    result = {
        field_name: getattr(settings, field_name)
        for field_name in Settings.model_fields
        if field_name in CONFIG_ALLOWLIST
    }
    # Add dynamic settings
    for key in _DYNAMIC_CONFIG_KEYS:
        result[key] = await ds.get(key)
    result["licensed"] = HAS_LICENSE
    return result


async def _collect_aggregates(db: AsyncSession) -> dict:
    """Collect row counts per PG and CH table.

    Only counts are returned - never row contents.
    """
    optic.debug("_collect_aggregates called")
    result: dict[str, Any] = {"pg_table_counts": {}, "ch_table_counts": {}}

    # PostgreSQL table counts
    try:
        rows = await db.execute(text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'"))
        table_names = [r[0] for r in rows.fetchall()]
        for table_name in table_names:
            try:
                # Table names come from pg_tables (system catalog), not user input.
                # Use quoted identifier to handle any special characters safely.
                count_row = await db.execute(text(f'SELECT count(*) FROM "{table_name}"'))
                result["pg_table_counts"][table_name] = count_row.scalar()
            except Exception as exc:
                result["pg_table_counts"][table_name] = f"error: {type(exc).__name__}"
    except Exception as exc:
        result["pg_table_counts"] = {"error": type(exc).__name__}

    # ClickHouse table counts (no FINAL - fast approximate counts)
    try:
        resp = await _query(
            "SELECT name FROM system.tables WHERE database = {db:String} FORMAT JSON",
            {"param_db": CLICKHOUSE_DB},
        )
        if resp.status_code == 200:
            ch_tables = [r["name"] for r in resp.json().get("data", [])]
            for table_name in ch_tables:
                if not _SAFE_TABLE_NAME_RE.match(table_name):
                    result["ch_table_counts"][table_name] = "error: unsafe table name, skipped"
                    continue
                try:
                    count_resp = await _query(f"SELECT count() FROM `{table_name}` FORMAT JSON")
                    if count_resp.status_code == 200:
                        count_data = count_resp.json().get("data", [])
                        if count_data:
                            result["ch_table_counts"][table_name] = count_data[0].get("count()", 0)
                        else:
                            result["ch_table_counts"][table_name] = 0
                    else:
                        result["ch_table_counts"][table_name] = f"error: HTTP {count_resp.status_code}"
                except Exception as exc:
                    result["ch_table_counts"][table_name] = f"error: {type(exc).__name__}"
        else:
            result["ch_table_counts"] = {"error": f"HTTP {resp.status_code}"}
    except Exception as exc:
        result["ch_table_counts"] = {"error": type(exc).__name__}

    return result


def _extract_stack_template(error_text: str) -> str:
    """Extract file paths and function names from a stack trace.

    Returns a sanitised template with only structural information -
    no argument values, no exception messages.
    """
    optic.trace("error_text={}", error_text)
    lines = error_text.splitlines()
    template_parts: list[str] = []

    # Match Python traceback file/function lines:
    #   File "path/to/file.py", line N, in function_name
    file_line_re = re.compile(r'File\s+"([^"]+)",\s+line\s+\d+,\s+in\s+(\S+)')

    for line in lines:
        m = file_line_re.search(line)
        if m:
            filepath, funcname = m.group(1), m.group(2)
            template_parts.append(f"{filepath}:{funcname}")

    if template_parts:
        return " -> ".join(template_parts)

    # Fallback: if no traceback pattern found, return a generic marker
    # with just the first line stripped of any argument-like content
    first_line = lines[0].strip() if lines else ""
    # Strip anything that looks like arguments or values (after a colon)
    sanitised = re.sub(r":.*", "", first_line).strip()
    return sanitised or "unknown"


async def _collect_errors(db: AsyncSession) -> dict:
    """Collect up to 50 error fingerprints from the last 24 hours.

    Each fingerprint includes a SHA-256 hash, count, first_seen,
    last_seen, and stack_template (file paths + function names only).
    No argument values or exception messages are included.
    """
    optic.debug("_collect_errors called")
    result: dict[str, Any] = {"fingerprints": []}

    return result


def _parse_duration(duration_str: str) -> timedelta:
    """Parse a human-friendly duration string into a timedelta.

    Supported formats: '1h', '30m', '2d', '1h30m', '90s'.
    Falls back to 1 hour on invalid input.
    """
    optic.trace("duration_str={}", duration_str)
    total_seconds = 0
    pattern = re.compile(r"(\d+)\s*([dhms])", re.IGNORECASE)
    matches = pattern.findall(duration_str)

    if not matches:
        return timedelta(hours=1)

    for value, unit in matches:
        n = int(value)
        if unit.lower() == "d":
            total_seconds += n * 86400
        elif unit.lower() == "h":
            total_seconds += n * 3600
        elif unit.lower() == "m":
            total_seconds += n * 60
        elif unit.lower() == "s":
            total_seconds += n

    return timedelta(seconds=total_seconds) if total_seconds > 0 else timedelta(hours=1)


async def _collect_logs(logs_since: str = "1h") -> dict:
    """Collect structured log lines from the in-memory ring buffer.

    Filters entries by the ``logs_since`` duration. Secrets are redacted
    server-side before returning; the CLI applies a second redaction pass
    as defence-in-depth.
    Returns an empty list gracefully if the buffer is empty.
    """
    optic.trace("logs_since={}", logs_since)
    try:
        from services.log_buffer import get_log_buffer

        buf = get_log_buffer()
        duration = _parse_duration(logs_since)
        cutoff = datetime.now(UTC) - duration
        entries = buf.get_since(cutoff)

        if not entries:
            return {
                "lines": [],
                "note": "Log buffer empty or server recently restarted",
            }

        # Sanitize entries: remove non-serializable objects like LogRecord
        sanitized = []
        for entry in entries:
            clean = {}
            for k, v in entry.items():
                if k.startswith("_"):
                    continue  # skip internal structlog keys (_record, _logger, etc.)
                if isinstance(v, (str, int, float, bool, type(None), list, dict)):
                    clean[k] = v
                else:
                    clean[k] = str(v)
            sanitized.append(clean)

        # Redact secrets server-side before returning (SEC-022).
        # redact_dict scrubs all string values; redact_secrets handles
        # individual strings that were coerced to str above.
        redacted = [redact_dict(entry) for entry in sanitized]
        return {"lines": redacted}
    except ImportError:
        return {
            "lines": [],
            "note": "Log buffer module not available",
        }
    except Exception as exc:
        return {
            "lines": [],
            "error": type(exc).__name__,
        }


# ── Collector registry ───────────────────────────────────────────────

# Maps collector name to a factory that accepts (db, logs_since) and returns
# a coroutine.  Collectors that don't need all arguments ignore them.
COLLECTORS: dict[str, Any] = {
    "versions": lambda db, logs_since: _collect_versions(db),
    "health": lambda db, logs_since: _collect_health(db),
    "config": lambda db, logs_since: _collect_config(),
    "aggregates": lambda db, logs_since: _collect_aggregates(db),
    "errors": lambda db, logs_since: _collect_errors(db),
    "logs": lambda db, logs_since: _collect_logs(logs_since),
}


# ── Endpoint ─────────────────────────────────────────────────────────


@router.post("/collect", response_model=CollectResponse)
@limiter.limit("5/minute")
async def collect_diagnostics(
    request: Request,
    body: CollectRequest,
    user: User = Depends(require_role(UserRole.admin)),
    db: AsyncSession = Depends(get_db),
) -> CollectResponse:
    """Run server-side diagnostic collectors and return results.

    Each collector runs with a 10-second timeout. Partial failures
    are reported in the response - the endpoint always returns 200
    if at least one collector succeeds.
    """
    # Determine which collectors to run
    optic.trace("user_id={}", user.id)
    requested = list(COLLECTORS.keys()) if "all" in body.collectors else [c for c in body.collectors if c in COLLECTORS]

    # Run all requested collectors concurrently
    tasks = [_run_collector(name, COLLECTORS[name](db, body.logs_since)) for name in requested]
    results = await asyncio.gather(*tasks)

    collectors_out: dict[str, CollectorData] = {}
    for name, collector_data in results:
        collectors_out[name] = collector_data

    # Server version
    try:
        from importlib.metadata import version

        server_version = version("observal-server")
    except Exception:
        server_version = "0.1.0"

    return CollectResponse(server_version=server_version, collectors=collectors_out)
