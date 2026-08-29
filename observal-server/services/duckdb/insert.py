# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: Apache-2.0
"""DuckDB insert functions for analytics tables.

Drop-in replacements for the legacy ClickHouse insert helpers. All function
signatures are unchanged; internals use parameterized batch inserts instead
of JSONEachRow-over-HTTP.

Dedup semantics: legacy ReplacingMergeTree(version) tables are DuckDB tables
with PRIMARY KEYs, written with INSERT OR REPLACE. Re-ingested rows (same PK)
overwrite prior versions at write time, so readers never need ClickHouse's
FINAL merge-on-read.
"""

import asyncio
import re
import time

from loguru import logger as optic

import services.duckdb.client as _client

_VALID_TABLE = re.compile(r"^[a-z_][a-z0-9_]*$")


def insert_rows(table: str, rows: list[dict], *, columns: list[str] | None = None, or_replace: bool = False) -> int:
    """Parameterized batch insert. Missing columns fall back to table defaults.

    Runs synchronously under the connection lock - call via asyncio.to_thread
    or from the async helpers below.

    Implementation note: rows are staged via an Arrow relation and merged in
    one set operation. DuckDB's executemany is a per-row prepared-statement
    loop (~2k rows/s) and row-by-row INSERT OR REPLACE against ART primary
    keys is similarly pathological; the Arrow scan + set merge is orders of
    magnitude faster and preserves DEFAULT semantics for unlisted columns.
    Falls back to a staged executemany merge when pyarrow is unavailable.
    """
    if not rows:
        return 0
    if not _VALID_TABLE.match(table):
        raise ValueError(f"invalid table name: {table!r}")
    with _client._lock:
        con = _client._get_con()
        if columns is None:
            columns = [r[1] for r in con.execute(f"PRAGMA table_info('{table}')").fetchall()]
        # Only insert columns the payload actually provides; the rest use the
        # column DEFAULT, matching ClickHouse JSONEachRow semantics.
        key_union: set[str] = set()
        for row in rows:
            key_union.update(row.keys())
        cols = [c for c in columns if c in key_union]
        col_sql = ", ".join(cols)
        verb = "INSERT OR REPLACE" if or_replace else "INSERT"
        projected = [{c: row.get(c) for c in cols} for row in rows]
        try:
            import pyarrow as pa
        except ImportError:
            pa = None
        if pa is not None:
            view = f"_stg_{table}"
            arrow = pa.Table.from_pylist(projected)
            con.register(view, arrow)
            try:
                con.execute(f"{verb} INTO {table} ({col_sql}) SELECT {col_sql} FROM {view}")
            finally:
                con.unregister(view)
        else:
            staging = f"_stg_{table}"
            placeholders = ", ".join("?" for _ in cols)
            values = [tuple(p[c] for c in cols) for p in projected]
            con.execute(f"DROP TABLE IF EXISTS {staging}")
            con.execute(f"CREATE TEMP TABLE {staging} AS SELECT {col_sql} FROM {table} LIMIT 0")
            try:
                con.executemany(f"INSERT INTO {staging} ({col_sql}) VALUES ({placeholders})", values)
                con.execute(f"{verb} INTO {table} ({col_sql}) SELECT {col_sql} FROM {staging}")
            finally:
                con.execute(f"DROP TABLE IF EXISTS {staging}")
        return len(projected)


_SESSION_EVENT_COLUMNS = [
    "session_id",
    "project_id",
    "user_id",
    "agent_id",
    "agent_version",
    "layer_hash",
    "harness",
    "line_offset",
    "source_end_offset",
    "line_hash",
    "source_sha256",
    "is_source_record",
    "rendered",
    "event_type",
    "timestamp",
    "uuid",
    "parent_uuid",
    "tool_name",
    "tool_id",
    "content_preview",
    "content_length",
    "raw_line",
    "credits",
    "parent_session_id",
    "input_tokens",
    "output_tokens",
    "cache_read_tokens",
    "cache_write_tokens",
    "model",
    "raw_line_truncated",
]

_AUDIT_COLUMNS = [
    "event_id",
    "timestamp",
    "actor_id",
    "actor_email",
    "actor_role",
    "action",
    "resource_type",
    "resource_id",
    "resource_name",
    "http_method",
    "http_path",
    "status_code",
    "ip_address",
    "user_agent",
    "detail",
    "sensitivity",
    "request_id",
    "outcome",
    "duration_ms",
    "chain_hash",
    "source",
]

_WEBHOOK_COLUMNS = [
    "delivery_id",
    "event_id",
    "alert_rule_id",
    "attempt_number",
    "timestamp",
    "webhook_url",
    "status_code",
    "delivery_status",
    "error",
    "duration_ms",
    "payload_size",
]

_CHECKPOINT_COLUMNS = [
    "session_id",
    "project_id",
    "user_id",
    "harness",
    "acknowledged_line",
    "acknowledged_offset",
    "checkpoint_version",
]

_LAYER_SNAPSHOT_COLUMNS = [
    "hash",
    "project_id",
    "user_id",
    "harness",
    "content",
    "file_count",
    "total_size",
    "lockfile_hash",
]


def _insert(table: str, columns: list[str], rows: list[dict], *, or_replace: bool = False) -> int:
    return insert_rows(table, rows, columns=columns, or_replace=or_replace)


async def insert_audit_log(events: list[dict]):
    """Batch insert audit log events."""
    optic.trace("inserting {} audit log events into DuckDB", len(events))
    if not events:
        return
    rows = []
    for e in events:
        rows.append(
            {
                "event_id": e["event_id"],
                "timestamp": e.get("timestamp") or _client._normalize_ts(e.get("timestamp")),
                "actor_id": e.get("actor_id", ""),
                "actor_email": e.get("actor_email", ""),
                "actor_role": e.get("actor_role", ""),
                "action": e.get("action", ""),
                "resource_type": e.get("resource_type", ""),
                "resource_id": e.get("resource_id", ""),
                "resource_name": e.get("resource_name", ""),
                "http_method": e.get("http_method", ""),
                "http_path": e.get("http_path", ""),
                "status_code": e.get("status_code", 0),
                "ip_address": e.get("ip_address", ""),
                "user_agent": e.get("user_agent", ""),
                "detail": e.get("detail", ""),
                "sensitivity": e.get("sensitivity", "standard"),
                "request_id": e.get("request_id", ""),
                "outcome": e.get("outcome", ""),
                "duration_ms": e.get("duration_ms", 0.0),
                "chain_hash": e.get("chain_hash", ""),
                "source": e.get("source", "server"),
            }
        )
    try:
        await asyncio.to_thread(_insert, "audit_log", _AUDIT_COLUMNS, rows)
    except Exception as exc:
        optic.error("failed to insert {} audit events into DuckDB - audit trail has a gap: {}", len(events), exc)


async def _insert_webhook_deliveries(records: list[dict]):
    """Batch insert webhook delivery records."""
    optic.trace("inserting {} webhook delivery records into DuckDB", len(records))
    if not records:
        return
    rows = []
    for r in records:
        rows.append(
            {
                "delivery_id": r["delivery_id"],
                "event_id": r["event_id"],
                "alert_rule_id": r["alert_rule_id"],
                "attempt_number": r["attempt_number"],
                "timestamp": _client._normalize_ts(r["timestamp"]),
                "webhook_url": r["webhook_url"],
                "status_code": r["status_code"],
                "delivery_status": r["delivery_status"],
                "error": r.get("error"),
                "duration_ms": r["duration_ms"],
                "payload_size": r["payload_size"],
            }
        )
    try:
        await asyncio.to_thread(_insert, "webhook_deliveries", _WEBHOOK_COLUMNS, rows)
    except Exception as exc:
        optic.error("failed to record {} webhook deliveries in DuckDB: {}", len(records), exc)


async def insert_session_events(rows: list[dict]):
    """Batch insert canonical session source rows.

    Dedup: INSERT OR REPLACE on (project_id, user_id, harness, session_id,
    line_offset) - the write-time replacement for ReplacingMergeTree.
    """
    optic.trace("inserting {} session events into DuckDB", len(rows))
    if not rows:
        return
    for row in rows:
        row.setdefault("source_end_offset", 0)
        row.setdefault("is_source_record", 1)
        row.setdefault("rendered", 1)
        row.setdefault("raw_line_truncated", 0)
        if row.get("timestamp") is not None:
            row["timestamp"] = _client._normalize_ts(row["timestamp"])
    try:
        await asyncio.to_thread(_insert, "session_events", _SESSION_EVENT_COLUMNS, rows, or_replace=True)
    except Exception as e:
        optic.error("failed to insert {} session events - session will appear incomplete: {}", len(rows), e)
        raise


async def insert_session_checkpoint(
    session_id: str,
    project_id: str,
    user_id: str,
    harness: str,
    acknowledged_line: int,
    acknowledged_offset: int,
) -> None:
    """Insert a replaceable checkpoint, including audit rewinds."""
    row = {
        "session_id": session_id,
        "project_id": project_id,
        "user_id": user_id,
        "harness": harness,
        "acknowledged_line": acknowledged_line,
        "acknowledged_offset": acknowledged_offset,
        "checkpoint_version": time.time_ns(),
    }
    resp = await asyncio.to_thread(
        _insert, "session_checkpoints", _CHECKPOINT_COLUMNS, [row], or_replace=True
    )
    if resp != 1:
        raise RuntimeError("checkpoint insert affected no rows")


async def refresh_session_summary(session_id: str, project_id: str, user_id: str, harness: str) -> None:
    """Replace one session summary from canonical deduplicated rows.

    Replaces the legacy ClickHouse materialized view + ReplacingMergeTree
    pipeline: the aggregate is recomputed from session_events and upserted.
    """
    sql = (
        "INSERT OR REPLACE INTO session_stats_agg "
        "(project_id, session_id, agent_id, agent_version, user_id, parent_session_id, harness, "
        "layer_hash, first_event_time, last_event_time, event_count, prompt_count, tool_call_count, "
        "tool_result_count, input_tokens, output_tokens, cache_read_tokens, cache_write_tokens, "
        "total_credits, model, summary_version, updated_at) "
        "SELECT project_id, session_id, "
        "coalesce(any_value(agent_id) FILTER (WHERE agent_id IS NOT NULL AND agent_id != ''), '') AS agent_id, "
        "coalesce(any_value(agent_version) FILTER (WHERE agent_version IS NOT NULL AND agent_version != ''), '') "
        "AS agent_version, "
        "user_id, coalesce(any_value(parent_session_id) FILTER (WHERE parent_session_id IS NOT NULL), '') "
        "AS parent_session_id, "
        "harness, coalesce(any_value(layer_hash) FILTER (WHERE layer_hash IS NOT NULL AND layer_hash != ''), '') "
        "AS layer_hash, "
        "min(timestamp) FILTER (WHERE rendered = 1 AND timestamp > '1971-01-01 00:00:00' "
        "AND timestamp < '2099-01-01 00:00:00') AS first_event_time, "
        "max(timestamp) FILTER (WHERE rendered = 1 AND timestamp > '1971-01-01 00:00:00' "
        "AND timestamp < '2099-01-01 00:00:00') AS last_event_time, "
        "count(*) FILTER (WHERE rendered = 1) AS event_count, "
        "count(*) FILTER (WHERE rendered = 1 AND event_type = 'user_prompt') AS prompt_count, "
        "count(*) FILTER (WHERE rendered = 1 AND event_type = 'tool_call') AS tool_call_count, "
        "count(*) FILTER (WHERE rendered = 1 AND event_type = 'tool_result') AS tool_result_count, "
        "coalesce(sum(input_tokens) FILTER (WHERE rendered = 1), 0) AS input_tokens, "
        "coalesce(sum(output_tokens) FILTER (WHERE rendered = 1), 0) AS output_tokens, "
        "coalesce(sum(cache_read_tokens) FILTER (WHERE rendered = 1), 0) AS cache_read_tokens, "
        "coalesce(sum(cache_write_tokens) FILTER (WHERE rendered = 1), 0) AS cache_write_tokens, "
        "coalesce(max(credits), 0) AS total_credits, "
        "coalesce(any_value(model) FILTER (WHERE rendered = 1 AND model != ''), '') AS model, "
        "epoch_ms(now()::TIMESTAMP)::UBIGINT AS summary_version, "
        "now()::TIMESTAMP AS updated_at "
        "FROM session_events WHERE project_id = $pid AND user_id = $uid "
        "AND harness = $harness AND session_id = $sid "
        "GROUP BY project_id, session_id, user_id, harness"
    )
    params = {"pid": project_id, "uid": user_id, "harness": harness, "sid": session_id}
    resp = await _client._query(sql, params)
    resp.raise_for_status()


async def insert_layer_snapshot(row: dict):
    """Insert (or replace) a single layer snapshot row."""
    optic.trace("inserting layer snapshot: hash={}", row.get("hash", "?"))
    try:
        await asyncio.to_thread(
            _insert, "layer_snapshots", _LAYER_SNAPSHOT_COLUMNS, [row], or_replace=True
        )
    except Exception as e:
        optic.error("failed to insert layer snapshot: {}", e)
        raise
