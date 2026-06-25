# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only
"""ClickHouse insert functions for live tables."""

import orjson
from loguru import logger as optic

import services.clickhouse.client as _client


def _dumps(obj: dict) -> str:
    return orjson.dumps(obj, default=str).decode()


async def insert_audit_log(events: list[dict]):
    """Batch insert audit log events into ClickHouse."""
    optic.trace("inserting {} audit log events into ClickHouse", len(events))
    if not events:
        return
    lines = []
    for e in events:
        row = {
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
            "org_id": e.get("org_id", ""),
            "sensitivity": e.get("sensitivity", "standard"),
            "request_id": e.get("request_id", ""),
            "outcome": e.get("outcome", ""),
            "duration_ms": e.get("duration_ms", 0.0),
            "chain_hash": e.get("chain_hash", ""),
            "source": e.get("source", "server"),
        }
        lines.append(_dumps(row))
    try:
        r = await _client._query(
            "INSERT INTO audit_log SETTINGS async_insert=0 FORMAT JSONEachRow", data="\n".join(lines)
        )
        r.raise_for_status()
    except Exception as exc:
        optic.error("failed to insert {} audit events into ClickHouse - audit trail has a gap: {}", len(events), exc)


async def _insert_webhook_deliveries(records: list[dict]):
    """Batch insert webhook delivery records into ClickHouse."""
    optic.trace("inserting {} webhook delivery records into ClickHouse", len(records))
    if not records:
        return
    lines = []
    for r in records:
        row = {
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
        lines.append(_dumps(row))
    sql = (
        "INSERT INTO webhook_deliveries (delivery_id, event_id, alert_rule_id, "
        "attempt_number, timestamp, webhook_url, status_code, delivery_status, "
        "error, duration_ms, payload_size) FORMAT JSONEachRow"
    )
    try:
        r = await _client._query(sql, data="\n".join(lines))
        r.raise_for_status()
    except Exception as exc:
        optic.error("failed to record {} webhook deliveries in ClickHouse: {}", len(records), exc)


async def insert_session_events(rows: list[dict]):
    """Batch insert session event rows into ClickHouse using JSONEachRow."""
    optic.trace("inserting {} session events into ClickHouse", len(rows))
    if not rows:
        return
    sql = (
        "INSERT INTO session_events (session_id, project_id, user_id, agent_id, "
        "agent_version, layer_hash, harness, line_offset, line_hash, event_type, timestamp, uuid, parent_uuid, "
        "tool_name, tool_id, content_preview, content_length, raw_line, credits, parent_session_id, "
        "input_tokens, output_tokens, cache_read_tokens, cache_write_tokens, model, raw_line_truncated) FORMAT JSONEachRow"
    )
    try:
        r = await _client._query(sql, data="\n".join(_dumps(row) for row in rows))
        r.raise_for_status()
    except Exception as e:
        optic.error("failed to insert {} session events - session will appear incomplete: {}", len(rows), e)
        raise


async def insert_layer_snapshot(row: dict):
    """Insert a single layer snapshot row into ClickHouse."""
    optic.trace("inserting layer snapshot: hash={}", row.get("hash", "?"))
    sql = (
        "INSERT INTO layer_snapshots (hash, project_id, user_id, harness, content, "
        "file_count, total_size, lockfile_hash) FORMAT JSONEachRow"
    )
    try:
        r = await _client._query(sql, data=_dumps(row))
        r.raise_for_status()
    except Exception as e:
        optic.error("failed to insert layer snapshot: {}", e)
        raise
