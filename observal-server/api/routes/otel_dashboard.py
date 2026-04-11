import logging

from fastapi import APIRouter

from services.clickhouse import _escape, _query

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/otel", tags=["otel-dashboard"])


async def _ch_json(sql: str, params: dict | None = None) -> list[dict]:
    try:
        r = await _query(f"{sql} FORMAT JSON", params)
        if r.status_code == 200:
            return r.json().get("data", [])
    except Exception as e:
        logger.warning(f"ClickHouse query failed: {e}")
    return []


@router.get("/sessions")
async def list_sessions():
    rows = await _ch_json(
        "SELECT "
        "LogAttributes['session.id'] AS session_id, "
        "min(Timestamp) AS first_event_time, "
        "max(Timestamp) AS last_event_time, "
        "countIf(EventName = 'user_prompt' OR LogAttributes['event.name'] = 'user_prompt') AS prompt_count, "
        "countIf(LogAttributes['event.name'] = 'api_request') AS api_request_count, "
        "countIf(LogAttributes['event.name'] = 'tool_result') AS tool_result_count, "
        "sum(toUInt64OrZero(LogAttributes['input_tokens'])) AS total_input_tokens, "
        "sum(toUInt64OrZero(LogAttributes['output_tokens'])) AS total_output_tokens, "
        "anyIf(LogAttributes['model'], LogAttributes['model'] != '') AS model, "
        "any(ServiceName) AS service_name "
        "FROM otel_logs "
        "WHERE LogAttributes['session.id'] != '' "
        "GROUP BY session_id "
        "ORDER BY last_event_time DESC "
        "LIMIT 100"
    )
    return rows


@router.get("/sessions/{session_id}")
async def get_session(session_id: str):
    sid = _escape(session_id)
    events = await _ch_json(
        "SELECT "
        "Timestamp AS timestamp, "
        "if(LogAttributes['event.name'] != '', LogAttributes['event.name'], EventName) AS event_name, "
        "Body AS body, "
        "LogAttributes AS attributes, "
        "ServiceName AS service_name "
        f"FROM otel_logs "
        f"WHERE LogAttributes['session.id'] = '{sid}' "
        "ORDER BY Timestamp ASC"
    )
    traces = await _ch_json(
        "SELECT "
        "TraceId AS trace_id, "
        "SpanId AS span_id, "
        "ParentSpanId AS parent_span_id, "
        "SpanName AS span_name, "
        "Duration AS duration_ns, "
        "StatusCode AS status_code, "
        "SpanAttributes AS span_attributes, "
        "Timestamp AS timestamp "
        f"FROM otel_traces "
        f"WHERE SpanAttributes['session.id'] = '{sid}' "
        "ORDER BY Timestamp ASC"
    )
    svc = events[0]["service_name"] if events else ""
    return {"session_id": session_id, "service_name": svc, "events": events, "traces": traces}


@router.get("/traces")
async def list_traces():
    rows = await _ch_json(
        "SELECT "
        "TraceId AS trace_id, "
        "SpanName AS span_name, "
        "ServiceName AS service_name, "
        "Duration AS duration_ns, "
        "StatusCode AS status, "
        "Timestamp AS timestamp, "
        "SpanAttributes['session.id'] AS session_id "
        "FROM otel_traces "
        "WHERE ParentSpanId = '' "
        "ORDER BY Timestamp DESC "
        "LIMIT 100"
    )
    return rows


@router.get("/traces/{trace_id}")
async def get_trace(trace_id: str):
    tid = _escape(trace_id)
    rows = await _ch_json(
        "SELECT "
        "SpanId AS span_id, "
        "ParentSpanId AS parent_span_id, "
        "SpanName AS span_name, "
        "Duration AS duration_ns, "
        "StatusCode AS status_code, "
        "SpanAttributes AS span_attributes, "
        "Events.Name AS event_names, "
        "Events.Timestamp AS event_timestamps, "
        "Events.Attributes AS event_attributes "
        f"FROM otel_traces "
        f"WHERE TraceId = '{tid}' "
        "ORDER BY Timestamp ASC"
    )
    spans = []
    for r in rows:
        events = []
        names = r.get("event_names") or []
        timestamps = r.get("event_timestamps") or []
        attrs = r.get("event_attributes") or []
        for i in range(len(names)):
            events.append(
                {
                    "name": names[i],
                    "timestamp": timestamps[i] if i < len(timestamps) else None,
                    "attributes": attrs[i] if i < len(attrs) else {},
                }
            )
        spans.append(
            {
                "span_id": r["span_id"],
                "parent_span_id": r["parent_span_id"],
                "span_name": r["span_name"],
                "duration_ns": r["duration_ns"],
                "status_code": r["status_code"],
                "span_attributes": r["span_attributes"],
                "events": events,
            }
        )
    return spans


@router.get("/stats")
async def otel_stats():
    log_rows = await _ch_json(
        "SELECT "
        "count(DISTINCT LogAttributes['session.id']) AS total_sessions, "
        "countIf(EventName = 'user_prompt' OR LogAttributes['event.name'] = 'user_prompt') AS total_prompts, "
        "countIf(LogAttributes['event.name'] = 'api_request') AS total_api_requests, "
        "countIf(LogAttributes['event.name'] = 'tool_result') AS total_tool_calls, "
        "sum(toUInt64OrZero(LogAttributes['input_tokens'])) AS total_input_tokens, "
        "sum(toUInt64OrZero(LogAttributes['output_tokens'])) AS total_output_tokens "
        "FROM otel_logs"
    )
    trace_rows = await _ch_json(
        "SELECT count(DISTINCT TraceId) AS total_traces, count() AS total_spans FROM otel_traces"
    )
    log = log_rows[0] if log_rows else {}
    tr = trace_rows[0] if trace_rows else {}
    return {
        "total_sessions": int(log.get("total_sessions", 0)),
        "total_prompts": int(log.get("total_prompts", 0)),
        "total_api_requests": int(log.get("total_api_requests", 0)),
        "total_tool_calls": int(log.get("total_tool_calls", 0)),
        "total_input_tokens": int(log.get("total_input_tokens", 0)),
        "total_output_tokens": int(log.get("total_output_tokens", 0)),
        "total_traces": int(tr.get("total_traces", 0)),
        "total_spans": int(tr.get("total_spans", 0)),
    }
