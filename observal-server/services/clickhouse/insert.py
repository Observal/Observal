# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only
"""ClickHouse insert functions for all telemetry tables."""

import orjson
from loguru import logger as optic

import services.clickhouse.client as _client


def _dumps(obj: dict) -> str:
    """Fast JSON serialization via orjson with str fallback for unknown types."""
    return orjson.dumps(obj, default=str).decode()


async def insert_traces(traces: list[dict]):
    """Batch insert traces into ClickHouse using JSONEachRow."""
    optic.trace("inserting {} traces into ClickHouse", len(traces))
    if not traces:
        return
    event_ts = _client._now_ms()
    lines = []
    for t in traces:
        row = {
            "trace_id": t["trace_id"],
            "parent_trace_id": t.get("parent_trace_id"),
            "project_id": t["project_id"],
            "mcp_id": t.get("mcp_id"),
            "agent_id": t.get("agent_id"),
            "user_id": t["user_id"],
            "session_id": t.get("session_id"),
            "ide": t.get("ide", ""),
            "environment": t.get("environment", "default"),
            "start_time": _client._normalize_ts(t["start_time"]),
            "end_time": _client._normalize_ts(t.get("end_time")),
            "trace_type": t.get("trace_type", "mcp"),
            "name": t.get("name", ""),
            "metadata": t.get("metadata", {}),
            "tags": t.get("tags", []),
            "input": t.get("input"),
            "output": t.get("output"),
            "event_ts": event_ts,
            "is_deleted": 0,
            "tool_id": t.get("tool_id"),
            "sandbox_id": t.get("sandbox_id"),
            "graphrag_id": t.get("graphrag_id"),
            "hook_id": t.get("hook_id"),
            "skill_id": t.get("skill_id"),
            "prompt_id": t.get("prompt_id"),
            "agent_version": t.get("agent_version"),
        }
        lines.append(_dumps(row))
    sql = (
        "INSERT INTO traces (trace_id, parent_trace_id, project_id, mcp_id, agent_id, "
        "user_id, session_id, ide, environment, start_time, end_time, trace_type, name, "
        "metadata, tags, input, output, event_ts, is_deleted, "
        "tool_id, sandbox_id, graphrag_id, hook_id, skill_id, prompt_id, "
        "agent_version) FORMAT JSONEachRow"
    )
    try:
        r = await _client._query(sql, data="\n".join(lines))
        r.raise_for_status()
    except Exception as e:
        optic.error("failed to insert {} traces into ClickHouse: {} - telemetry data is lost", len(traces), e)
        raise


async def insert_spans(spans: list[dict]):
    """Batch insert spans into ClickHouse using JSONEachRow."""
    optic.trace("inserting {} spans into ClickHouse", len(spans))
    if not spans:
        return
    event_ts = _client._now_ms()
    lines = []
    for s in spans:
        row = {
            "span_id": s["span_id"],
            "trace_id": s["trace_id"],
            "parent_span_id": s.get("parent_span_id"),
            "project_id": s["project_id"],
            "mcp_id": s.get("mcp_id"),
            "agent_id": s.get("agent_id"),
            "user_id": s["user_id"],
            "type": s["type"],
            "name": s["name"],
            "method": s.get("method", ""),
            "input": s.get("input"),
            "output": s.get("output"),
            "error": s.get("error"),
            "start_time": _client._normalize_ts(s["start_time"]),
            "end_time": _client._normalize_ts(s.get("end_time")),
            "latency_ms": s.get("latency_ms"),
            "status": s.get("status", "success"),
            "level": s.get("level", "DEFAULT"),
            "token_count_input": s.get("token_count_input"),
            "token_count_output": s.get("token_count_output"),
            "token_count_total": s.get("token_count_total"),
            "cost": s.get("cost"),
            "cpu_ms": s.get("cpu_ms"),
            "memory_mb": s.get("memory_mb"),
            "hop_count": s.get("hop_count"),
            "entities_retrieved": s.get("entities_retrieved"),
            "relationships_used": s.get("relationships_used"),
            "retry_count": s.get("retry_count"),
            "tools_available": s.get("tools_available"),
            "tool_schema_valid": s.get("tool_schema_valid"),
            "ide": s.get("ide", ""),
            "environment": s.get("environment", "default"),
            "metadata": s.get("metadata", {}),
            "event_ts": event_ts,
            "is_deleted": 0,
            "container_id": s.get("container_id"),
            "exit_code": s.get("exit_code"),
            "network_bytes_in": s.get("network_bytes_in"),
            "network_bytes_out": s.get("network_bytes_out"),
            "disk_read_bytes": s.get("disk_read_bytes"),
            "disk_write_bytes": s.get("disk_write_bytes"),
            "oom_killed": s.get("oom_killed"),
            "query_interface": s.get("query_interface"),
            "relevance_score": s.get("relevance_score"),
            "chunks_returned": s.get("chunks_returned"),
            "embedding_latency_ms": s.get("embedding_latency_ms"),
            "hook_event": s.get("hook_event"),
            "hook_scope": s.get("hook_scope"),
            "hook_action": s.get("hook_action"),
            "hook_blocked": s.get("hook_blocked"),
            "variables_provided": s.get("variables_provided"),
            "template_tokens": s.get("template_tokens"),
            "rendered_tokens": s.get("rendered_tokens"),
            "agent_version": s.get("agent_version"),
        }
        lines.append(_dumps(row))
    sql = (
        "INSERT INTO spans (span_id, trace_id, parent_span_id, project_id, mcp_id, "
        "agent_id, user_id, type, name, method, input, output, error, start_time, "
        "end_time, latency_ms, status, level, token_count_input, token_count_output, "
        "token_count_total, cost, cpu_ms, memory_mb, hop_count, entities_retrieved, "
        "relationships_used, retry_count, tools_available, tool_schema_valid, ide, "
        "environment, metadata, event_ts, is_deleted, "
        "container_id, exit_code, network_bytes_in, network_bytes_out, "
        "disk_read_bytes, disk_write_bytes, oom_killed, query_interface, "
        "relevance_score, chunks_returned, embedding_latency_ms, "
        "hook_event, hook_scope, hook_action, hook_blocked, "
        "variables_provided, template_tokens, rendered_tokens, "
        "agent_version) FORMAT JSONEachRow"
    )
    try:
        r = await _client._query(sql, data="\n".join(lines))
        r.raise_for_status()
    except Exception as e:
        optic.error("failed to insert {} spans into ClickHouse: {} - span data is lost", len(spans), e)
        raise


async def insert_scores(scores: list[dict]):
    """Batch insert scores into ClickHouse using JSONEachRow."""
    optic.trace("inserting {} scores into ClickHouse", len(scores))
    if not scores:
        return
    event_ts = _client._now_ms()
    lines = []
    for sc in scores:
        row = {
            "score_id": sc["score_id"],
            "trace_id": sc.get("trace_id"),
            "span_id": sc.get("span_id"),
            "project_id": sc["project_id"],
            "mcp_id": sc.get("mcp_id"),
            "agent_id": sc.get("agent_id"),
            "user_id": sc["user_id"],
            "name": sc["name"],
            "source": sc.get("source", "api"),
            "data_type": sc.get("data_type", "numeric"),
            "value": sc.get("value", 0),
            "string_value": sc.get("string_value"),
            "comment": sc.get("comment"),
            "eval_template_id": sc.get("eval_template_id"),
            "eval_config_id": sc.get("eval_config_id"),
            "eval_run_id": sc.get("eval_run_id"),
            "environment": sc.get("environment", "default"),
            "metadata": sc.get("metadata", {}),
            "timestamp": _client._normalize_ts(sc["timestamp"]),
            "event_ts": event_ts,
            "is_deleted": 0,
            "agent_version": sc.get("agent_version"),
        }
        lines.append(_dumps(row))
    sql = (
        "INSERT INTO scores (score_id, trace_id, span_id, project_id, mcp_id, agent_id, "
        "user_id, name, source, data_type, value, string_value, comment, "
        "eval_template_id, eval_config_id, eval_run_id, environment, metadata, "
        "timestamp, event_ts, is_deleted, agent_version) FORMAT JSONEachRow"
    )
    try:
        r = await _client._query(sql, data="\n".join(lines))
        r.raise_for_status()
        await _client._invalidate_cache()
    except Exception as e:
        optic.error("failed to insert {} scores into ClickHouse: {}", len(scores), e)
        raise


async def insert_otel_logs(rows: list[dict]):
    """Batch insert rows into the otel_logs table (OTEL Collector schema)."""
    optic.trace("inserting {} OTEL log rows into ClickHouse", len(rows))
    if not rows:
        return
    lines = []
    for r in rows:
        line = {
            "Timestamp": _client._normalize_ts(r["Timestamp"]),
            "Body": r.get("Body", ""),
            "LogAttributes": r.get("LogAttributes", {}),
            "ServiceName": r.get("ServiceName", ""),
            "SeverityText": r.get("SeverityText", "INFO"),
            "SeverityNumber": r.get("SeverityNumber", 9),
            "TraceId": r.get("TraceId", ""),
            "SpanId": r.get("SpanId", ""),
        }
        lines.append(_dumps(line))
    sql = (
        "INSERT INTO otel_logs (Timestamp, Body, LogAttributes, ServiceName, "
        "SeverityText, SeverityNumber, TraceId, SpanId) FORMAT JSONEachRow"
    )
    try:
        r = await _client._query(sql, data="\n".join(lines))
        r.raise_for_status()
    except Exception as e:
        optic.error("failed to insert {} OTEL logs into ClickHouse: {}", len(rows), e)
        raise


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
    body = "\n".join(lines)
    sql = "INSERT INTO audit_log FORMAT JSONEachRow SETTINGS async_insert=0"
    try:
        r = await _client._query(sql, data=body)
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
    body = "\n".join(lines)
    sql = (
        "INSERT INTO webhook_deliveries (delivery_id, event_id, alert_rule_id, "
        "attempt_number, timestamp, webhook_url, status_code, delivery_status, "
        "error, duration_ms, payload_size) FORMAT JSONEachRow"
    )
    try:
        r = await _client._query(sql, data=body)
        r.raise_for_status()
    except Exception as exc:
        optic.error("failed to record {} webhook deliveries in ClickHouse: {}", len(records), exc)


async def insert_session_events(rows: list[dict]):
    """Batch insert session event rows into ClickHouse using JSONEachRow."""
    optic.trace("inserting {} session events into ClickHouse", len(rows))
    if not rows:
        return
    lines = []
    for row in rows:
        lines.append(_dumps(row))
    sql = (
        "INSERT INTO session_events (session_id, project_id, user_id, agent_id, "
        "agent_version, layer_hash, ide, line_offset, line_hash, event_type, timestamp, uuid, parent_uuid, "
        "tool_name, tool_id, content_preview, content_length, raw_line, credits, parent_session_id, "
        "input_tokens, output_tokens, cache_read_tokens, cache_write_tokens, model, raw_line_truncated) FORMAT JSONEachRow"
    )
    try:
        r = await _client._query(sql, data="\n".join(lines))
        r.raise_for_status()
    except Exception as e:
        optic.error("failed to insert {} session events - session will appear incomplete: {}", len(rows), e)
        raise


async def insert_layer_snapshot(row: dict):
    """Insert a single layer snapshot row into ClickHouse."""
    optic.trace("inserting layer snapshot: hash={}", row.get("hash", "?"))
    sql = (
        "INSERT INTO layer_snapshots (hash, project_id, user_id, ide, content, "
        "file_count, total_size, lockfile_hash) FORMAT JSONEachRow"
    )
    try:
        r = await _client._query(sql, data=_dumps(row))
        r.raise_for_status()
    except Exception as e:
        optic.error("failed to insert layer snapshot: {}", e)
        raise
