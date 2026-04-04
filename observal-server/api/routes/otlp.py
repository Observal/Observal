"""OTLP HTTP receiver for native OpenTelemetry exporters.

Accepts standard OTLP JSON on /v1/traces, /v1/logs, /v1/metrics and converts
to Observal's internal ClickHouse format.  Authentication is optional: callers
may pass ``Authorization: Bearer <key>`` but unauthenticated requests are
accepted by default (OTLP exporters rarely carry API keys).
"""

import json
import logging
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Request, Response

from services.clickhouse import insert_spans, insert_traces

logger = logging.getLogger(__name__)

router = APIRouter(prefix="", tags=["otlp"])

DEFAULT_PROJECT = "default"
_DT_FMT = "%Y-%m-%d %H:%M:%S.%f"

# OTLP status codes
_STATUS_MAP = {0: "success", 1: "success", 2: "error"}

# IDE detection from resource attributes
_IDE_HINTS = {
    "claude-code": "claude_code",
    "claude code": "claude_code",
    "gemini": "gemini_cli",
    "copilot": "github_copilot",
    "cursor": "cursor",
    "kiro": "kiro",
    "windsurf": "windsurf",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _nanos_to_dt(nanos: str | int) -> str:
    """Convert nanosecond unix timestamp to datetime string."""
    ts = int(nanos) / 1e9
    return datetime.fromtimestamp(ts, tz=UTC).strftime(_DT_FMT)[:-3]


def _nanos_to_ms(start: str | int, end: str | int) -> int | None:
    """Calculate latency in ms from two nano timestamps."""
    try:
        return max(0, int((int(end) - int(start)) / 1_000_000))
    except (ValueError, TypeError):
        return None


def _extract_attrs(attributes: list[dict]) -> dict[str, str]:
    """Flatten OTLP attribute list to a simple dict."""
    out: dict[str, str] = {}
    for attr in attributes:
        key = attr.get("key", "")
        val = attr.get("value", {})
        if "stringValue" in val:
            out[key] = val["stringValue"]
        elif "intValue" in val:
            out[key] = str(val["intValue"])
        elif "doubleValue" in val:
            out[key] = str(val["doubleValue"])
        elif "boolValue" in val:
            out[key] = str(val["boolValue"]).lower()
        elif "arrayValue" in val:
            out[key] = json.dumps(val["arrayValue"].get("values", []))
    return out


def _detect_ide(attrs: dict[str, str]) -> str:
    """Best-effort IDE detection from resource/span attributes."""
    for field in ("service.name", "telemetry.sdk.name", "process.runtime.name", "terminal.type"):
        val = attrs.get(field, "").lower()
        for hint, ide in _IDE_HINTS.items():
            if hint in val:
                return ide
    return attrs.get("terminal.type", "")


def _safe_int(val: str | None) -> int | None:
    if val is None:
        return None
    try:
        return int(val)
    except (ValueError, TypeError):
        return None


def _safe_float(val: str | None) -> float | None:
    if val is None:
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def _now_ms() -> str:
    return datetime.now(UTC).strftime(_DT_FMT)[:-3]


# ---------------------------------------------------------------------------
# OTLP Trace conversion
# ---------------------------------------------------------------------------


def _convert_resource_spans(body: dict) -> tuple[list[dict], list[dict]]:
    """Parse OTLP resourceSpans into Observal trace and span rows."""
    traces: list[dict] = []
    spans: list[dict] = []
    seen_traces: dict[str, dict] = {}

    for rs in body.get("resourceSpans", []):
        res_attrs = _extract_attrs(rs.get("resource", {}).get("attributes", []))
        ide = _detect_ide(res_attrs)

        for ss in rs.get("scopeSpans", []):
            for span in ss.get("spans", []):
                try:
                    span_attrs = _extract_attrs(span.get("attributes", []))
                    all_attrs = {**res_attrs, **span_attrs}

                    trace_id = span.get("traceId", "")
                    span_id = span.get("spanId", "")
                    parent_span_id = span.get("parentSpanId") or None
                    name = span.get("name", "")
                    start_nano = span.get("startTimeUnixNano", "0")
                    end_nano = span.get("endTimeUnixNano", "0")
                    start_time = _nanos_to_dt(start_nano)
                    end_time = _nanos_to_dt(end_nano) if int(end_nano) > 0 else None
                    latency_ms = _nanos_to_ms(start_nano, end_nano)

                    status_code = span.get("status", {}).get("code", 0)
                    status = _STATUS_MAP.get(status_code, "success")
                    error_msg = span.get("status", {}).get("message") if status == "error" else None

                    user_id = all_attrs.get("user.id") or all_attrs.get("user.email") or all_attrs.get("user.account_uuid") or "otlp"
                    session_id = all_attrs.get("session.id")

                    # GenAI semantic conventions
                    input_text = all_attrs.get("gen_ai.prompt")
                    output_text = all_attrs.get("gen_ai.completion")
                    tok_in = _safe_int(all_attrs.get("gen_ai.usage.input_tokens"))
                    tok_out = _safe_int(all_attrs.get("gen_ai.usage.output_tokens"))
                    tok_total = (tok_in or 0) + (tok_out or 0) if (tok_in is not None or tok_out is not None) else None
                    cost = _safe_float(all_attrs.get("gen_ai.usage.cost"))

                    # Metadata: carry over interesting attributes
                    metadata: dict[str, str] = {}
                    prompt_id = all_attrs.get("prompt.id")
                    if prompt_id:
                        metadata["prompt_id"] = prompt_id
                    model = all_attrs.get("gen_ai.request.model") or all_attrs.get("gen_ai.response.model")
                    if model:
                        metadata["model"] = model

                    span_type = "otlp"
                    kind = span.get("kind", 0)
                    if kind == 3:  # CLIENT
                        span_type = "llm" if model else "client"
                    elif kind == 2:  # SERVER
                        span_type = "server"
                    elif kind == 1:  # INTERNAL
                        span_type = "internal"

                    span_row = {
                        "span_id": span_id,
                        "trace_id": trace_id,
                        "parent_span_id": parent_span_id,
                        "project_id": DEFAULT_PROJECT,
                        "mcp_id": None,
                        "agent_id": None,
                        "user_id": user_id,
                        "type": span_type,
                        "name": name,
                        "method": "",
                        "input": input_text,
                        "output": output_text,
                        "error": error_msg,
                        "start_time": start_time,
                        "end_time": end_time,
                        "latency_ms": latency_ms,
                        "status": status,
                        "ide": ide,
                        "environment": "default",
                        "metadata": metadata,
                        "token_count_input": tok_in,
                        "token_count_output": tok_out,
                        "token_count_total": tok_total,
                        "cost": cost,
                    }
                    spans.append(span_row)

                    # Process span events (Claude Code specifics)
                    _process_span_events(span, trace_id, span_id, all_attrs, ide, user_id, spans)

                    # Collect root-level trace (no parent = root span)
                    if not parent_span_id and trace_id not in seen_traces:
                        seen_traces[trace_id] = {
                            "trace_id": trace_id,
                            "project_id": DEFAULT_PROJECT,
                            "user_id": user_id,
                            "session_id": session_id,
                            "ide": ide,
                            "environment": "default",
                            "start_time": start_time,
                            "end_time": end_time,
                            "trace_type": "otlp",
                            "name": name,
                            "metadata": metadata,
                            "tags": [],
                            "input": input_text,
                            "output": output_text,
                        }
                except Exception:
                    logger.warning("Failed to convert OTLP span", exc_info=True)

    traces = list(seen_traces.values())
    return traces, spans


def _process_span_events(
    span: dict,
    trace_id: str,
    parent_span_id: str,
    all_attrs: dict[str, str],
    ide: str,
    user_id: str,
    spans_out: list[dict],
):
    """Extract Claude Code span events into child spans."""
    for event in span.get("events", []):
        try:
            event_name = event.get("name", "")
            event_attrs = _extract_attrs(event.get("attributes", []))
            event_time = event.get("timeUnixNano", "0")
            dt = _nanos_to_dt(event_time) if int(event_time) > 0 else _now_ms()

            if event_name in ("claude_code.user_prompt", "user_prompt"):
                # Captured as trace input via log handler; also emit a span
                spans_out.append({
                    "span_id": uuid.uuid4().hex,
                    "trace_id": trace_id,
                    "parent_span_id": parent_span_id,
                    "project_id": DEFAULT_PROJECT,
                    "user_id": user_id,
                    "type": "user_prompt",
                    "name": "user_prompt",
                    "input": event_attrs.get("prompt") or event_attrs.get("content"),
                    "start_time": dt,
                    "end_time": dt,
                    "status": "success",
                    "ide": ide,
                    "environment": "default",
                    "metadata": {},
                })
            elif event_name in ("claude_code.tool_result", "tool_result"):
                dur = _safe_int(event_attrs.get("duration_ms"))
                spans_out.append({
                    "span_id": uuid.uuid4().hex,
                    "trace_id": trace_id,
                    "parent_span_id": parent_span_id,
                    "project_id": DEFAULT_PROJECT,
                    "user_id": user_id,
                    "type": "tool_result",
                    "name": event_attrs.get("tool_name", "tool"),
                    "output": event_attrs.get("result"),
                    "start_time": dt,
                    "end_time": dt,
                    "latency_ms": dur,
                    "status": "success" if event_attrs.get("success", "true") == "true" else "error",
                    "ide": ide,
                    "environment": "default",
                    "metadata": {},
                })
            elif event_name in ("claude_code.api_request", "api_request"):
                tok_in = _safe_int(event_attrs.get("input_tokens"))
                tok_out = _safe_int(event_attrs.get("output_tokens"))
                tok_total = (tok_in or 0) + (tok_out or 0) if (tok_in is not None or tok_out is not None) else None
                meta: dict[str, str] = {}
                if event_attrs.get("model"):
                    meta["model"] = event_attrs["model"]
                spans_out.append({
                    "span_id": uuid.uuid4().hex,
                    "trace_id": trace_id,
                    "parent_span_id": parent_span_id,
                    "project_id": DEFAULT_PROJECT,
                    "user_id": user_id,
                    "type": "llm",
                    "name": event_attrs.get("model", "api_request"),
                    "start_time": dt,
                    "end_time": dt,
                    "latency_ms": _safe_int(event_attrs.get("duration_ms")),
                    "status": "success",
                    "ide": ide,
                    "environment": "default",
                    "metadata": meta,
                    "token_count_input": tok_in,
                    "token_count_output": tok_out,
                    "token_count_total": tok_total,
                    "cost": _safe_float(event_attrs.get("cost")),
                })
        except Exception:
            logger.warning("Failed to process span event %s", event.get("name"), exc_info=True)


# ---------------------------------------------------------------------------
# OTLP Log conversion
# ---------------------------------------------------------------------------


def _convert_resource_logs(body: dict) -> tuple[list[dict], list[dict]]:
    """Parse OTLP resourceLogs into Observal trace and span rows."""
    traces: list[dict] = []
    spans: list[dict] = []
    # Group by prompt_id to build traces
    prompt_traces: dict[str, dict] = {}

    for rl in body.get("resourceLogs", []):
        res_attrs = _extract_attrs(rl.get("resource", {}).get("attributes", []))
        ide = _detect_ide(res_attrs)

        for sl in rl.get("scopeLogs", []):
            for rec in sl.get("logRecords", []):
                try:
                    log_attrs = _extract_attrs(rec.get("attributes", []))
                    all_attrs = {**res_attrs, **log_attrs}
                    event_name = all_attrs.get("event.name", "")
                    print(f"OTLP log: event_name={repr(event_name)}, all_attr_keys={list(all_attrs.keys())[:15]}", flush=True)
                    time_nano = rec.get("timeUnixNano", "0")
                    dt = _nanos_to_dt(time_nano) if int(time_nano) > 0 else _now_ms()

                    user_id = all_attrs.get("user.id") or all_attrs.get("user.email") or all_attrs.get("user.account_uuid") or "otlp"
                    session_id = all_attrs.get("session.id")
                    prompt_id = all_attrs.get("prompt.id")
                    # Use prompt_id as trace grouping key, fall back to a new UUID
                    trace_id = prompt_id or uuid.uuid4().hex

                    body_val = rec.get("body", {})
                    body_text = body_val.get("stringValue", "") if isinstance(body_val, dict) else str(body_val)

                    if event_name in ("claude_code.user_prompt", "user_prompt"):
                        prompt_text = all_attrs.get("prompt") or body_text or all_attrs.get("content") or all_attrs.get("prompt_length")
                        logger.info("OTLP user_prompt: prompt_text=%s, body_text=%s, attrs=%s", repr(prompt_text)[:200], repr(body_text)[:200], {k: repr(v)[:80] for k, v in all_attrs.items() if k.startswith("prompt") or k == "event.name"})
                        # Create or update trace with user prompt as input
                        if trace_id not in prompt_traces:
                            prompt_traces[trace_id] = {
                                "trace_id": trace_id,
                                "project_id": DEFAULT_PROJECT,
                                "user_id": user_id,
                                "session_id": session_id,
                                "ide": ide,
                                "environment": "default",
                                "start_time": dt,
                                "trace_type": "otlp",
                                "name": "user_prompt",
                                "metadata": {"prompt_id": prompt_id} if prompt_id else {},
                                "tags": [],
                                "input": prompt_text,
                            }
                        else:
                            prompt_traces[trace_id]["input"] = prompt_text

                    elif event_name in ("claude_code.tool_result", "tool_result"):
                        # Ensure trace exists
                        if trace_id not in prompt_traces:
                            prompt_traces[trace_id] = {
                                "trace_id": trace_id,
                                "project_id": DEFAULT_PROJECT,
                                "user_id": user_id,
                                "session_id": session_id,
                                "ide": ide,
                                "environment": "default",
                                "start_time": dt,
                                "trace_type": "otlp",
                                "name": "session",
                                "metadata": {"prompt_id": prompt_id} if prompt_id else {},
                                "tags": [],
                            }
                        dur = _safe_int(all_attrs.get("duration_ms"))
                        spans.append({
                            "span_id": uuid.uuid4().hex,
                            "trace_id": trace_id,
                            "project_id": DEFAULT_PROJECT,
                            "user_id": user_id,
                            "type": "tool_result",
                            "name": all_attrs.get("tool_name", "tool"),
                            "output": body_text or all_attrs.get("result"),
                            "start_time": dt,
                            "end_time": dt,
                            "latency_ms": dur,
                            "status": "success" if all_attrs.get("success", "true") == "true" else "error",
                            "ide": ide,
                            "environment": "default",
                            "metadata": {},
                        })

                    elif event_name in ("claude_code.api_request", "api_request"):
                        if trace_id not in prompt_traces:
                            prompt_traces[trace_id] = {
                                "trace_id": trace_id,
                                "project_id": DEFAULT_PROJECT,
                                "user_id": user_id,
                                "session_id": session_id,
                                "ide": ide,
                                "environment": "default",
                                "start_time": dt,
                                "trace_type": "otlp",
                                "name": "session",
                                "metadata": {"prompt_id": prompt_id} if prompt_id else {},
                                "tags": [],
                            }
                        tok_in = _safe_int(all_attrs.get("input_tokens"))
                        tok_out = _safe_int(all_attrs.get("output_tokens"))
                        tok_total = (tok_in or 0) + (tok_out or 0) if (tok_in is not None or tok_out is not None) else None
                        meta: dict[str, str] = {}
                        if all_attrs.get("model"):
                            meta["model"] = all_attrs["model"]
                        spans.append({
                            "span_id": uuid.uuid4().hex,
                            "trace_id": trace_id,
                            "project_id": DEFAULT_PROJECT,
                            "user_id": user_id,
                            "type": "llm",
                            "name": all_attrs.get("model", "api_request"),
                            "start_time": dt,
                            "end_time": dt,
                            "latency_ms": _safe_int(all_attrs.get("duration_ms")),
                            "status": "success",
                            "ide": ide,
                            "environment": "default",
                            "metadata": meta,
                            "token_count_input": tok_in,
                            "token_count_output": tok_out,
                            "token_count_total": tok_total,
                            "cost": _safe_float(all_attrs.get("cost")),
                        })
                    else:
                        # Generic log record → span
                        spans.append({
                            "span_id": uuid.uuid4().hex,
                            "trace_id": trace_id,
                            "project_id": DEFAULT_PROJECT,
                            "user_id": user_id,
                            "type": "log",
                            "name": event_name or "log",
                            "input": body_text or None,
                            "start_time": dt,
                            "end_time": dt,
                            "status": "success",
                            "ide": ide,
                            "environment": "default",
                            "metadata": {"severity": str(rec.get("severityNumber", ""))} if rec.get("severityNumber") else {},
                        })
                except Exception:
                    logger.warning("Failed to convert OTLP log record", exc_info=True)

    traces = list(prompt_traces.values())
    print(f"OTLP logs converted: {len(traces)} traces, {len(spans)} spans, prompt_traces_keys={list(prompt_traces.keys())[:5]}", flush=True)
    if traces:
        print(f"OTLP first trace: name={traces[0].get('name')}, input={repr(traces[0].get('input'))[:100]}, session={traces[0].get('session_id')}", flush=True)
    return traces, spans


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

_OTLP_OK = {"partialSuccess": {}}


@router.post("/v1/traces")
async def otlp_traces(request: Request):
    """Receive OTLP trace export (JSON)."""
    try:
        body = await request.json()
    except Exception:
        logger.warning("OTLP /v1/traces: malformed JSON body")
        return Response(content=json.dumps({"partialSuccess": {"rejectedSpans": 1, "errorMessage": "malformed JSON"}}), status_code=400, media_type="application/json")

    try:
        trace_rows, span_rows = _convert_resource_spans(body)
    except Exception:
        logger.warning("OTLP /v1/traces: conversion failed", exc_info=True)
        return Response(content=json.dumps(_OTLP_OK), status_code=200, media_type="application/json")

    errors = 0
    if trace_rows:
        try:
            await insert_traces(trace_rows)
        except Exception:
            logger.exception("OTLP: insert_traces failed")
            errors += len(trace_rows)
    if span_rows:
        try:
            await insert_spans(span_rows)
        except Exception:
            logger.exception("OTLP: insert_spans failed")
            errors += len(span_rows)

    if errors:
        return Response(
            content=json.dumps({"partialSuccess": {"rejectedSpans": errors}}),
            status_code=200,
            media_type="application/json",
        )
    return Response(content=json.dumps(_OTLP_OK), status_code=200, media_type="application/json")


@router.post("/v1/logs")
async def otlp_logs(request: Request):
    """Receive OTLP log export (JSON)."""
    try:
        body = await request.json()
    except Exception:
        logger.warning("OTLP /v1/logs: malformed JSON body")
        return Response(content=json.dumps({"partialSuccess": {"rejectedLogRecords": 1, "errorMessage": "malformed JSON"}}), status_code=400, media_type="application/json")

    rl_count = len(body.get("resourceLogs", []))
    total_recs = sum(len(rec) for rl in body.get("resourceLogs", []) for sl in rl.get("scopeLogs", []) for rec in [sl.get("logRecords", [])])
    print(f"OTLP /v1/logs: {rl_count} resourceLogs, {total_recs} total records", flush=True)
    if rl_count > 0:
        sample = body["resourceLogs"][0]
        print(f"OTLP /v1/logs sample resource attrs: {[a.get('key') for a in sample.get('resource', {}).get('attributes', [])][:10]}", flush=True)
        for sl in sample.get("scopeLogs", []):
            for rec in sl.get("logRecords", [])[:3]:
                print(f"OTLP /v1/logs sample record: body={repr(rec.get('body', {}))[:200]}, attrs={[a.get('key') for a in rec.get('attributes', [])][:15]}", flush=True)

    try:
        trace_rows, span_rows = _convert_resource_logs(body)
    except Exception:
        logger.warning("OTLP /v1/logs: conversion failed", exc_info=True)
        return Response(content=json.dumps(_OTLP_OK), status_code=200, media_type="application/json")

    errors = 0
    if trace_rows:
        try:
            await insert_traces(trace_rows)
        except Exception:
            logger.exception("OTLP: insert_traces from logs failed")
            errors += len(trace_rows)
    if span_rows:
        try:
            await insert_spans(span_rows)
        except Exception:
            logger.exception("OTLP: insert_spans from logs failed")
            errors += len(span_rows)

    if errors:
        return Response(
            content=json.dumps({"partialSuccess": {"rejectedLogRecords": errors}}),
            status_code=200,
            media_type="application/json",
        )
    return Response(content=json.dumps(_OTLP_OK), status_code=200, media_type="application/json")


@router.post("/v1/metrics")
async def otlp_metrics(request: Request):
    """Receive OTLP metrics export (JSON). Best-effort: extract token/cost counters."""
    try:
        body = await request.json()
    except Exception:
        logger.warning("OTLP /v1/metrics: malformed JSON body")
        return Response(content=json.dumps({"partialSuccess": {"rejectedDataPoints": 1, "errorMessage": "malformed JSON"}}), status_code=400, media_type="application/json")

    span_rows: list[dict] = []
    now = _now_ms()

    for rm in body.get("resourceMetrics", []):
        res_attrs = _extract_attrs(rm.get("resource", {}).get("attributes", []))
        ide = _detect_ide(res_attrs)
        user_id = res_attrs.get("user.id") or res_attrs.get("user.email") or "otlp"

        for sm in rm.get("scopeMetrics", []):
            for metric in sm.get("metrics", []):
                try:
                    name = metric.get("name", "")
                    # Extract data points from sum, gauge, or histogram
                    points = []
                    for kind in ("sum", "gauge"):
                        if kind in metric:
                            points.extend(metric[kind].get("dataPoints", []))
                    if "histogram" in metric:
                        points.extend(metric["histogram"].get("dataPoints", []))

                    for dp in points:
                        dp_attrs = _extract_attrs(dp.get("attributes", []))
                        val = dp.get("asDouble") or dp.get("asInt") or dp.get("sum")
                        if val is None:
                            continue
                        meta = {"metric_name": name, **dp_attrs}
                        tok_in = _safe_int(dp_attrs.get("gen_ai.usage.input_tokens")) if "token" in name.lower() else None
                        tok_out = _safe_int(dp_attrs.get("gen_ai.usage.output_tokens")) if "token" in name.lower() else None
                        span_rows.append({
                            "span_id": uuid.uuid4().hex,
                            "trace_id": uuid.uuid4().hex,
                            "project_id": DEFAULT_PROJECT,
                            "user_id": user_id,
                            "type": "metric",
                            "name": name,
                            "start_time": now,
                            "end_time": now,
                            "status": "success",
                            "ide": ide,
                            "environment": "default",
                            "metadata": {k: str(v) for k, v in meta.items()},
                            "token_count_input": tok_in,
                            "token_count_output": tok_out,
                            "cost": _safe_float(dp_attrs.get("cost")),
                        })
                except Exception:
                    logger.warning("Failed to convert OTLP metric %s", metric.get("name"), exc_info=True)

    if span_rows:
        try:
            await insert_spans(span_rows)
        except Exception:
            logger.exception("OTLP: insert_spans from metrics failed")
            return Response(
                content=json.dumps({"partialSuccess": {"rejectedDataPoints": len(span_rows)}}),
                status_code=200,
                media_type="application/json",
            )

    return Response(content=json.dumps(_OTLP_OK), status_code=200, media_type="application/json")
