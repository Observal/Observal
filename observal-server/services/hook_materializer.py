"""Materializer: converts otel_logs hook events into eval-compatible spans.

Kiro CLI (and other hook-based sources) write flat log entries to otel_logs.
The eval pipeline expects structured spans with type/input/output/status.
This module bridges that gap by reading hook events for a session and
synthesizing span dicts that StructuralScorer and SLMScorer can consume.

Also provides agent-scoped annotation: given a full session, marks which
spans belong to a target agent so the eval pipeline can focus its scoring.
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime

import structlog

from services.clickhouse import _query, query_shim_spans_for_window

logger = structlog.get_logger(__name__)

_SERVICE_NAME_MAP: dict[str, str] = {
    "kiro-cli": "kiro",
    "observal-hooks": "claude-code",
    "observal-shim": "claude-code",
}


def _normalize_service(svc: str) -> str:
    return _SERVICE_NAME_MAP.get(svc, svc)


@dataclass
class AgentContext:
    """Describes an agent's participation within a session."""

    agent_id: str = ""
    agent_type: str = ""
    agent_name: str = ""
    delegation_prompt: str = ""
    agent_output: str = ""
    span_start_idx: int = -1
    span_end_idx: int = -1
    invocations: list[dict] = field(default_factory=list)


async def materialize_session_spans(session_id: str) -> tuple[dict, list[dict]]:
    """Convert otel_logs hook events for a session into a trace + spans.

    Returns:
        (trace_dict, spans_list) compatible with run_structured_eval().
    """
    events = await _fetch_session_events(session_id)
    if not events:
        return {}, []

    return _build_trace_and_spans(session_id, events)


async def materialize_agent_eval(
    session_id: str,
    target_agent: str,
) -> tuple[dict, list[dict], AgentContext | None]:
    """Materialize a full session and annotate spans for a target agent.

    Returns:
        (trace_dict, all_spans, agent_context) where agent_context describes
        the target agent's participation. all_spans include an 'agent_id'
        field on each span so the eval pipeline knows which belong to the
        target agent. Returns (trace, spans, None) if agent not found.
    """
    events = await _fetch_session_events(session_id)
    if not events:
        return {}, [], None

    trace, spans = _build_trace_and_spans(session_id, events)
    if not spans:
        return trace, spans, None

    agent_ctx = _find_agent_context(spans, target_agent)
    return trace, spans, agent_ctx


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _fetch_session_events(session_id: str) -> list[dict]:
    """Fetch all otel_logs events for a session, with shim span side-load."""
    sql = (
        "SELECT "
        "Timestamp AS timestamp, "
        "LogAttributes['event.name'] AS event_name, "
        "Body AS body, "
        "LogAttributes AS attributes, "
        "ServiceName AS service_name "
        "FROM otel_logs "
        "WHERE LogAttributes['session.id'] = {sid:String} "
        "ORDER BY Timestamp ASC "
        "FORMAT JSON"
    )
    params = {"param_sid": session_id}

    try:
        r = await _query(sql, params)
        r.raise_for_status()
        events = r.json().get("data", [])
    except Exception as e:
        logger.error("hook_events_fetch_failed", session_id=session_id, error=str(e))
        return []

    if not events:
        return events

    # Side-load shim spans from the spans table (for when OBSERVAL_SESSION_ID
    # is not set — the common case for both Claude Code and Kiro).
    events = await _sideload_shim_for_eval(events)
    return events


# Shim span type → otel_logs event.name
_SHIM_TYPE_TO_EVENT: dict[str, str] = {
    "tool_call": "shim_tool_call",
    "tool_list": "shim_tool_list",
    "initialize": "shim_initialize",
    "resource_read": "shim_resource_read",
    "resource_list": "shim_resource_list",
    "resource_subscribe": "shim_resource_subscribe",
    "prompt_get": "shim_prompt_get",
    "prompt_list": "shim_prompt_list",
    "ping": "shim_ping",
    "completion": "shim_completion",
    "config": "shim_config",
    "other": "shim_other",
}


async def _sideload_shim_for_eval(events: list[dict]) -> list[dict]:
    """Side-load shim spans from spans table into otel_logs event list.

    Same strategy as otel_dashboard._sideload_shim_spans() but for the
    eval pipeline.  Extracts user_id + time bounds from events, queries
    the spans table, and synthesizes otel_logs-shaped events.
    """
    import json as _json

    user_id = ""
    min_ts = ""
    max_ts = ""
    session_service = ""
    existing_shim_span_ids: set[str] = set()

    for e in events:
        attrs = e.get("attributes", {})
        if isinstance(attrs, str):
            try:
                attrs = _json.loads(attrs)
            except Exception:
                attrs = {}
        if not user_id and attrs.get("user.id"):
            user_id = attrs["user.id"]
        ts = e.get("timestamp", "")
        if ts:
            if not min_ts or ts < min_ts:
                min_ts = ts
            if not max_ts or ts > max_ts:
                max_ts = ts
        if attrs.get("source") == "shim" and attrs.get("mcp_span_id"):
            existing_shim_span_ids.add(attrs["mcp_span_id"])
        svc = e.get("service_name", "")
        if svc and svc != "observal-shim" and not session_service:
            session_service = svc

    if not user_id or not min_ts or not max_ts:
        return events

    shim_spans = await query_shim_spans_for_window(user_id, min_ts, max_ts)
    if not shim_spans:
        return events

    svc_name = _normalize_service(session_service) or "claude-code"
    synthetic: list[dict] = []
    for s in shim_spans:
        span_id = s.get("span_id", "")
        if span_id in existing_shim_span_ids:
            continue

        span_type = s.get("type", "other")
        event_name = _SHIM_TYPE_TO_EVENT.get(span_type, "shim_other")
        tool_name = s.get("name", "")
        latency_ms = s.get("latency_ms")

        latency_label = f" ({latency_ms}ms)" if latency_ms else ""
        body_text = f"shim: {span_type} {tool_name}{latency_label}"

        attrs: dict[str, str] = {
            "event.name": event_name,
            "source": "shim",
            "tool_name": tool_name,
            "mcp_id": s.get("mcp_id", "") or "",
            "mcp_method": s.get("method", ""),
            "mcp_span_id": span_id,
            "mcp_trace_id": s.get("trace_id", ""),
        }
        if latency_ms is not None:
            attrs["mcp_latency_ms"] = str(latency_ms)
        if s.get("tool_schema_valid") is not None:
            attrs["tool_schema_valid"] = str(s["tool_schema_valid"])
        if s.get("tools_available") is not None:
            attrs["tools_available"] = str(s["tools_available"])
        if s.get("input"):
            attrs["mcp_input"] = str(s["input"])[:2000]
        if s.get("output"):
            attrs["mcp_output"] = str(s["output"])[:2000]
        if s.get("error"):
            attrs["mcp_error"] = str(s["error"])[:2000]
        if s.get("status"):
            attrs["mcp_status"] = s["status"]

        synthetic.append(
            {
                "timestamp": s.get("start_time", ""),
                "event_name": event_name,
                "body": body_text,
                "attributes": attrs,
                "service_name": svc_name,
            }
        )

    if not synthetic:
        return events

    combined = events + synthetic
    combined.sort(key=lambda e: e.get("timestamp", ""))
    return combined


def _parse_attrs(event: dict) -> dict:
    """Extract and normalize the attributes dict from an event."""
    attrs = event.get("attributes", {})
    if isinstance(attrs, str):
        import json

        try:
            attrs = json.loads(attrs)
        except Exception:
            attrs = {}
    return attrs


def _build_trace_and_spans(session_id: str, events: list[dict]) -> tuple[dict, list[dict]]:
    """Parse hook events into a trace dict and span list.

    Each span is tagged with agent_id/agent_type if the source event
    carried that attribution (Claude Code does this for subagent scopes).
    SubagentStart/SubagentStop are also materialized as spans.
    """
    spans: list[dict] = []
    trace_output = ""
    model = ""
    agent_name = ""
    first_ts = events[0].get("timestamp", "")
    last_ts = events[-1].get("timestamp", "")

    pending_pre: dict | None = None

    for event in events:
        attrs = _parse_attrs(event)

        event_name = _normalize_event_name(attrs.get("event.name", event.get("event_name", "")))

        if not model and attrs.get("model"):
            model = attrs["model"]
        if not agent_name and attrs.get("agent_name"):
            agent_name = attrs["agent_name"]

        # Common agent attribution from the event
        span_agent_id = attrs.get("agent_id", "")
        span_agent_type = attrs.get("agent_type", "")

        if event_name in ("hook_PreToolUse", "PreToolUse"):
            pending_pre = {
                "timestamp": event.get("timestamp", ""),
                "tool_name": attrs.get("tool_name", "unknown"),
                "tool_input": attrs.get("tool_input", event.get("body", "")),
                "agent_id": span_agent_id,
                "agent_type": span_agent_type,
            }

        elif event_name in ("hook_PostToolUse", "PostToolUse", "hook_PostToolUseFailure"):
            tool_name = attrs.get("tool_name", "")
            tool_input = ""
            tool_output = attrs.get("tool_response", event.get("body", ""))
            start_ts = event.get("timestamp", "")
            is_error = "Failure" in event_name or attrs.get("error", "")

            if pending_pre:
                tool_name = tool_name or pending_pre["tool_name"]
                tool_input = pending_pre["tool_input"]
                start_ts = pending_pre["timestamp"]
                span_agent_id = span_agent_id or pending_pre["agent_id"]
                span_agent_type = span_agent_type or pending_pre["agent_type"]
                pending_pre = None

            latency_ms = _compute_latency(start_ts, event.get("timestamp", ""))

            span = {
                "span_id": str(uuid.uuid4())[:16],
                "type": "tool_call",
                "name": tool_name,
                "input": _truncate(tool_input, 2000),
                "output": _truncate(tool_output, 2000),
                "status": "error" if is_error else "success",
                "error": attrs.get("error", "") if is_error else None,
                "latency_ms": latency_ms,
                "start_time": start_ts,
                "agent_id": span_agent_id,
                "agent_type": span_agent_type,
            }

            # MCP enrichment from merged shim data
            if attrs.get("mcp_id"):
                span["mcp_id"] = attrs["mcp_id"]
            if attrs.get("tool_schema_valid"):
                span["tool_schema_valid"] = int(attrs["tool_schema_valid"])
            if attrs.get("mcp_latency_ms"):
                span["mcp_latency_ms"] = int(attrs["mcp_latency_ms"])

            spans.append(span)

        elif event_name in ("shim_tool_call",):
            # Shim-only tool call (no matching hook event)
            tool_name = attrs.get("tool_name", "")
            span = {
                "span_id": str(uuid.uuid4())[:16],
                "type": "tool_call",
                "name": tool_name,
                "input": _truncate(attrs.get("mcp_input", ""), 2000),
                "output": _truncate(attrs.get("mcp_output", ""), 2000),
                "status": "error" if attrs.get("mcp_status") == "error" else "success",
                "error": attrs.get("mcp_error") if attrs.get("mcp_status") == "error" else None,
                "latency_ms": int(attrs["mcp_latency_ms"]) if attrs.get("mcp_latency_ms") else 0,
                "start_time": event.get("timestamp", ""),
                "agent_id": span_agent_id,
                "agent_type": span_agent_type,
                "mcp_id": attrs.get("mcp_id", ""),
                "tool_schema_valid": int(attrs["tool_schema_valid"]) if attrs.get("tool_schema_valid") else None,
                "mcp_latency_ms": int(attrs["mcp_latency_ms"]) if attrs.get("mcp_latency_ms") else None,
            }
            spans.append(span)

        elif event_name in ("hook_UserPromptSubmit", "UserPromptSubmit", "user_prompt"):
            prompt_text = attrs.get("tool_input", "") or attrs.get("prompt", "") or event.get("body", "")
            spans.append(
                {
                    "span_id": str(uuid.uuid4())[:16],
                    "type": "user_prompt",
                    "name": "user_prompt",
                    "input": _truncate(prompt_text, 2000),
                    "output": "",
                    "status": "success",
                    "error": None,
                    "latency_ms": 0,
                    "start_time": event.get("timestamp", ""),
                    "agent_id": span_agent_id,
                    "agent_type": span_agent_type,
                }
            )

        elif event_name in ("hook_subagentstart", "hook_SubagentStart"):
            delegation = attrs.get("tool_input", event.get("body", ""))
            spans.append(
                {
                    "span_id": str(uuid.uuid4())[:16],
                    "type": "subagent_start",
                    "name": f"SubagentStart:{span_agent_type or span_agent_id}",
                    "input": _truncate(delegation, 2000),
                    "output": "",
                    "status": "success",
                    "error": None,
                    "latency_ms": 0,
                    "start_time": event.get("timestamp", ""),
                    "agent_id": span_agent_id,
                    "agent_type": span_agent_type,
                }
            )

        elif event_name in ("hook_subagentstop", "hook_SubagentStop"):
            agent_output = attrs.get("tool_response", event.get("body", ""))
            spans.append(
                {
                    "span_id": str(uuid.uuid4())[:16],
                    "type": "subagent_stop",
                    "name": f"SubagentStop:{span_agent_type or span_agent_id}",
                    "input": "",
                    "output": _truncate(agent_output, 2000),
                    "status": "success",
                    "error": None,
                    "latency_ms": 0,
                    "start_time": event.get("timestamp", ""),
                    "agent_id": span_agent_id,
                    "agent_type": span_agent_type,
                }
            )

        elif event_name in ("hook_Stop", "Stop"):
            response = attrs.get("tool_response", "") or attrs.get("assistant_response", "") or event.get("body", "")
            trace_output = _truncate(response, 4000)
            spans.append(
                {
                    "span_id": str(uuid.uuid4())[:16],
                    "type": "agent_response",
                    "name": "final_response",
                    "input": "",
                    "output": trace_output,
                    "status": "success",
                    "error": None,
                    "latency_ms": 0,
                    "start_time": event.get("timestamp", ""),
                    "agent_id": span_agent_id,
                    "agent_type": span_agent_type,
                }
            )

        elif event_name in ("hook_SessionStart", "SessionStart", "agentSpawn"):
            spans.append(
                {
                    "span_id": str(uuid.uuid4())[:16],
                    "type": "session_start",
                    "name": "session_start",
                    "input": event.get("body", ""),
                    "output": "",
                    "status": "success",
                    "error": None,
                    "latency_ms": 0,
                    "start_time": event.get("timestamp", ""),
                    "agent_id": span_agent_id,
                    "agent_type": span_agent_type,
                }
            )

    # Build the trace dict
    trace = {
        "trace_id": session_id,
        "event_id": session_id,
        "agent_id": agent_name,
        "model": model,
        "output": trace_output,
        "status": "completed",
        "start_time": first_ts,
        "end_time": last_ts,
        "span_count": len(spans),
        "tool_calls": sum(1 for s in spans if s["type"] == "tool_call"),
        "source": "hook_materializer",
    }

    return trace, spans


def _find_agent_context(spans: list[dict], target_agent: str) -> AgentContext | None:
    """Find all invocations of a target agent within a session's spans.

    Matches by agent_id, agent_type, or agent_name (case-insensitive).
    Returns an AgentContext with all invocations listed, or None if not found.
    """
    target_lower = target_agent.lower()
    ctx = AgentContext()

    # Find SubagentStart/Stop boundaries for this agent
    invocations: list[dict] = []
    current_invocation: dict | None = None

    for idx, span in enumerate(spans):
        agent_match = (
            (span.get("agent_id") or "").lower() == target_lower
            or (span.get("agent_type") or "").lower() == target_lower
            or (span.get("agent_name") or "").lower() == target_lower
        )

        if span["type"] == "subagent_start" and agent_match:
            current_invocation = {
                "start_idx": idx,
                "end_idx": idx,
                "delegation_prompt": span.get("input", ""),
                "agent_output": "",
            }
            if not ctx.agent_id:
                ctx.agent_id = span.get("agent_id", "")
                ctx.agent_type = span.get("agent_type", "")
                ctx.agent_name = span.get("agent_type") or span.get("agent_id", "")

        elif span["type"] == "subagent_stop" and agent_match and current_invocation:
            current_invocation["end_idx"] = idx
            current_invocation["agent_output"] = span.get("output", "")
            invocations.append(current_invocation)
            current_invocation = None

        elif current_invocation is not None and agent_match:
            # Span within an active invocation — extend the boundary
            current_invocation["end_idx"] = idx

    # If we found SubagentStart/Stop boundaries, use those
    if invocations:
        ctx.invocations = invocations
        ctx.delegation_prompt = invocations[0]["delegation_prompt"]
        ctx.agent_output = invocations[-1]["agent_output"]
        ctx.span_start_idx = invocations[0]["start_idx"]
        ctx.span_end_idx = invocations[-1]["end_idx"]
        return ctx

    # Fallback: no SubagentStart/Stop but spans carry agent_id attribution
    agent_span_indices = [
        idx
        for idx, span in enumerate(spans)
        if (
            (span.get("agent_id") or "").lower() == target_lower
            or (span.get("agent_type") or "").lower() == target_lower
        )
        and span["type"] not in ("session_start",)
    ]

    if agent_span_indices:
        ctx.span_start_idx = agent_span_indices[0]
        ctx.span_end_idx = agent_span_indices[-1]
        ctx.agent_id = target_agent
        ctx.invocations = [
            {
                "start_idx": agent_span_indices[0],
                "end_idx": agent_span_indices[-1],
                "delegation_prompt": "",
                "agent_output": "",
            }
        ]
        return ctx

    return None


def build_agent_eval_context(
    spans: list[dict],
    agent_ctx: AgentContext,
) -> dict:
    """Build the context dict that the eval pipeline uses for agent-scoped scoring.

    Returns a dict with:
    - full_spans: all session spans (for SLM context)
    - agent_spans: only the target agent's spans (for structural scoring)
    - agent_span_indices: set of indices belonging to the agent
    - delegation_prompt: what the agent was asked to do
    - agent_output: what the agent returned
    - invocations: list of all invocations with boundaries
    """
    agent_indices: set[int] = set()
    for inv in agent_ctx.invocations:
        agent_indices.update(range(inv["start_idx"], inv["end_idx"] + 1))

    agent_spans = [spans[i] for i in sorted(agent_indices) if i < len(spans)]

    return {
        "full_spans": spans,
        "agent_spans": agent_spans,
        "agent_span_indices": agent_indices,
        "delegation_prompt": agent_ctx.delegation_prompt,
        "agent_output": agent_ctx.agent_output,
        "invocations": agent_ctx.invocations,
        "agent_id": agent_ctx.agent_id,
        "agent_type": agent_ctx.agent_type,
    }


# ---------------------------------------------------------------------------
# Event normalization and utilities
# ---------------------------------------------------------------------------


def _normalize_event_name(name: str) -> str:
    """Normalize event names to a consistent form."""
    if name.startswith("hook_") or name in (
        "PreToolUse",
        "PostToolUse",
        "UserPromptSubmit",
        "Stop",
        "SessionStart",
    ):
        return name
    mapping = {
        "preToolUse": "PreToolUse",
        "postToolUse": "PostToolUse",
        "userPromptSubmit": "UserPromptSubmit",
        "stop": "Stop",
        "agentSpawn": "SessionStart",
    }
    return mapping.get(name, name)


def _compute_latency(start: str, end: str) -> int:
    """Compute latency in ms between two ISO timestamps."""
    try:
        fmt = "%Y-%m-%d %H:%M:%S.%f"
        for f in (fmt, "%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"):
            try:
                t_start = datetime.strptime(start[:26], f)
                t_end = datetime.strptime(end[:26], f)
                return max(0, int((t_end - t_start).total_seconds() * 1000))
            except ValueError:
                continue
    except Exception:
        pass
    return 0


def _truncate(text: str, max_len: int) -> str:
    """Truncate text to max_len chars."""
    if not text:
        return ""
    text = str(text)
    return text[:max_len] if len(text) > max_len else text
