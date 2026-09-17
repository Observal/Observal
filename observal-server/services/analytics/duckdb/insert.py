# SPDX-FileCopyrightText: 2026 Observal contributors
# SPDX-FileCopyrightText: 2026 Srihari <sriharilegend23@gmail.com>
# SPDX-License-Identifier: Apache-2.0
"""DuckDB insert functions for live analytics tables."""

from __future__ import annotations

import time

from loguru import logger as optic

import services.analytics.duckdb.client as _client


async def insert_security_events(events: list[dict]) -> None:
    """Batch insert security events."""
    if not events:
        return
    try:
        await _client._insert(
            "security_events",
            [{**event, "timestamp": _client._normalize_ts(event.get("timestamp"))} for event in events],
        )
    except Exception as exc:
        optic.error("failed to insert {} security events: {}", len(events), exc)


async def insert_audit_log(events: list[dict]) -> None:
    """Batch insert audit log events."""
    optic.trace("inserting {} audit log events into analytics", len(events))
    if not events:
        return
    rows = [
        {
            "event_id": e["event_id"],
            "timestamp": _client._normalize_ts(e.get("timestamp")),
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
        for e in events
    ]
    try:
        await _client._insert("audit_log", rows)
    except Exception as exc:
        optic.error("failed to insert {} audit events - audit trail has a gap: {}", len(events), exc)


async def _insert_webhook_deliveries(records: list[dict]) -> None:
    """Batch insert webhook delivery records."""
    optic.trace("inserting {} webhook delivery records into analytics", len(records))
    if not records:
        return
    rows = [
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
        for r in records
    ]
    try:
        await _client._insert("webhook_deliveries", rows)
    except Exception as exc:
        optic.error("failed to record {} webhook deliveries: {}", len(records), exc)


async def insert_session_events(rows: list[dict]) -> None:
    """Batch insert canonical session source rows."""
    optic.trace("inserting {} session events into analytics", len(rows))
    if not rows:
        return
    for row in rows:
        row.setdefault("source_end_offset", 0)
        row.setdefault("is_source_record", 1)
        row.setdefault("rendered", 1)
        row.setdefault("raw_line_truncated", 0)
        # The Arrow batch always carries every column, so an omitted
        # ingested_at would be written as NULL instead of the DDL default.
        row.setdefault("ingested_at", _client._now_ms())
    try:
        await _client._insert("session_events", rows)
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
    await _client._insert("session_checkpoints", [row])


async def refresh_session_summary(session_id: str, project_id: str, user_id: str, harness: str) -> None:
    """Replace one session summary from canonical rows.

    ClickHouse maintained this through ``session_stats_mv`` plus an explicit
    recomputation; DuckDB has no materialized views, so the recomputation is
    the only path.
    """
    sql = """
        INSERT OR REPLACE INTO session_stats_agg
        SELECT
            project_id,
            session_id,
            coalesce(max(agent_id) FILTER (WHERE agent_id IS NOT NULL AND agent_id != ''), '') AS agent_id,
            coalesce(max(agent_version) FILTER (WHERE agent_version IS NOT NULL AND agent_version != ''), '') AS agent_version,
            user_id,
            coalesce(max(parent_session_id) FILTER (WHERE parent_session_id IS NOT NULL), '') AS parent_session_id,
            harness,
            coalesce(max(layer_hash) FILTER (WHERE layer_hash IS NOT NULL AND layer_hash != ''), '') AS layer_hash,
            min(timestamp) FILTER (
                WHERE rendered = 1 AND timestamp > TIMESTAMP '1971-01-01 00:00:00' AND timestamp < TIMESTAMP '2099-01-01 00:00:00'
            ) AS first_event_time,
            max(timestamp) FILTER (
                WHERE rendered = 1 AND timestamp > TIMESTAMP '1971-01-01 00:00:00' AND timestamp < TIMESTAMP '2099-01-01 00:00:00'
            ) AS last_event_time,
            count(*) FILTER (WHERE rendered = 1) AS event_count,
            count(*) FILTER (WHERE rendered = 1 AND event_type = 'user_prompt') AS prompt_count,
            count(*) FILTER (WHERE rendered = 1 AND event_type = 'tool_call') AS tool_call_count,
            count(*) FILTER (WHERE rendered = 1 AND event_type = 'tool_result') AS tool_result_count,
            coalesce(sum(input_tokens) FILTER (WHERE rendered = 1), 0) AS input_tokens,
            coalesce(sum(output_tokens) FILTER (WHERE rendered = 1), 0) AS output_tokens,
            coalesce(sum(cache_read_tokens) FILTER (WHERE rendered = 1), 0) AS cache_read_tokens,
            coalesce(sum(cache_write_tokens) FILTER (WHERE rendered = 1), 0) AS cache_write_tokens,
            coalesce(max(credits), 0) AS total_credits,
            coalesce(max(model) FILTER (WHERE rendered = 1 AND model != ''), '') AS model,
            CAST(epoch_ms(now()) AS UBIGINT) AS summary_version,
            now() AS updated_at
        FROM session_events
        WHERE project_id = $pid AND user_id = $uid AND harness = $harness AND session_id = $sid
        GROUP BY project_id, session_id, user_id, harness
    """
    params = {"pid": project_id, "uid": user_id, "harness": harness, "sid": session_id}
    await _client._execute(sql, params)


async def insert_layer_snapshot(row: dict) -> None:
    """Insert a single layer snapshot row."""
    optic.trace("inserting layer snapshot: hash={}", row.get("hash", "?"))
    try:
        await _client._insert("layer_snapshots", [row])
    except Exception as e:
        optic.error("failed to insert layer snapshot: {}", e)
        raise
