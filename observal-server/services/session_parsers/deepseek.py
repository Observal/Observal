# SPDX-FileCopyrightText: 2026 Observal Contributors
# SPDX-License-Identifier: Apache-2.0

"""DeepSeek Harness v4 JSONL session rows for the trace viewer.

Only committed messages produce transcript text. Embedded assistant streams are
attempt evidence, not additional messages; tool calls are separate log events.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

from .base import basic_event, dict_field, list_field, load_line, str_field, strip_ansi


def epoch_ms_timestamp(value: object) -> str | None:
    """Convert a nonnegative Unix-millisecond timestamp to ClickHouse UTC format."""
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    try:
        return (
            datetime.fromtimestamp(value // 1000, tz=UTC)
            .replace(microsecond=value % 1000 * 1000)
            .strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        )
    except (OverflowError, OSError, ValueError):
        return None


def _event(ts: str, harness: str, name: str, body: str, attrs: dict) -> dict:
    return {
        "timestamp": ts,
        "event_name": name,
        "body": body[:100],
        "attributes": attrs,
        "service_name": harness,
    }


def _text(message: dict) -> tuple[str, str]:
    text: list[str] = []
    reasoning: list[str] = []
    for block in list_field(message, "content"):
        if not isinstance(block, dict):
            continue
        kind = str_field(block, "type")
        if kind == "text":
            text.append(str_field(block, "text"))
        elif kind == "reasoning":
            reasoning.append(str_field(block, "text"))
    return strip_ansi("\n".join(text)), strip_ansi("\n".join(reasoning))


def _usage(data: dict) -> dict[str, str]:
    usage = dict_field(data, "usage")
    attrs: dict[str, str] = {}
    for field, key in (
        ("inputTokens", "input_tokens"),
        ("outputTokens", "output_tokens"),
        ("totalTokens", "total_tokens"),
        ("cacheReadTokens", "cache_read_tokens"),
        ("cacheWriteTokens", "cache_creation_tokens"),
        ("reasoningTokens", "reasoning_tokens"),
    ):
        value = usage.get(field)
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            attrs[key] = str(value)
    source = dict_field(dict_field(data, "message"), "source")
    for field in ("model", "provider"):
        value = str_field(source, field)
        if value:
            attrs[field] = value
    return attrs


def _context(line: dict, data: dict) -> dict[str, str]:
    attrs: dict[str, str] = {}
    for field in ("seq", "turn", "step"):
        value = line.get(field) if field == "seq" else data.get(field)
        if isinstance(value, int) and not isinstance(value, bool):
            attrs[field] = str(value)
    op = line.get("surfaceOp")
    if op == "append":
        attrs["surface_op"] = "append"
    elif isinstance(op, dict) and str_field(op, "op") == "replace":
        attrs["surface_op"] = "replace"
        for key in ("startSeq", "endSeq"):
            value = op.get(key)
            if isinstance(value, int) and not isinstance(value, bool):
                attrs[key] = str(value)
    seqs = line.get("sourceEventSeqs")
    if isinstance(seqs, list) and all(isinstance(seq, int) and not isinstance(seq, bool) for seq in seqs):
        attrs["source_event_seqs"] = json.dumps(seqs)
    return attrs


def _attempt_failure(data: dict) -> dict:
    for record in list_field(data, "stream"):
        if not isinstance(record, dict) or str_field(record, "type") != "chunk":
            continue
        chunk = dict_field(record, "chunk")
        if str_field(chunk, "type") == "finish":
            reason = dict_field(chunk, "reason")
            if str_field(reason, "kind") in ("error", "aborted"):
                return reason
    return {}


def parse_rows(rows: list[dict]) -> list[dict]:
    """Render v4 records, pairing results by call ID while keeping orphan results."""
    events: list[dict] = []
    calls: dict[str, int] = {}
    for row in rows:
        raw_line = row.get("raw_line")
        line = load_line(raw_line) if isinstance(raw_line, str) else None
        if line is None:
            events.append(basic_event(row))
            continue
        kind = str_field(line, "type")
        data = dict_field(line, "data")
        ts = epoch_ms_timestamp(line.get("createdAt") if kind == "session" else line.get("time"))
        row_ts = row.get("timestamp")
        ts = ts or (row_ts if isinstance(row_ts, str) and not row_ts.startswith("1970-01-01") else None)
        ts = ts or row.get("ingested_at") or ""
        harness = row.get("harness", "deepseek")
        attrs = _context(line, data)

        if kind == "session":
            for key in ("id", "cwd", "parentSession", "origin", "agentPreset"):
                value = str_field(line, key)
                if value:
                    attrs[key] = value
            for key in ("version", "delegationDepth"):
                value = line.get(key)
                if isinstance(value, int) and not isinstance(value, bool):
                    attrs[key] = str(value)
            events.append(_event(ts, harness, "hook_sessionstart", "Session started", attrs))
        elif kind in ("turn/start", "turn/end"):
            if kind == "turn/end":
                reason = dict_field(data, "reason")
                attrs["reason"] = str_field(reason, "kind")
                failure = dict_field(reason, "error")
                for field in ("code", "message"):
                    value = str_field(failure, field)
                    if value:
                        attrs[f"error_{field}"] = value
            body = f"Turn {attrs.get('turn', '')} {'started' if kind == 'turn/start' else 'ended'}"
            events.append(
                _event(ts, harness, "hook_sessionstart" if kind == "turn/start" else "hook_stop", body, attrs)
            )
        elif kind in ("user/message", "system/message", "developer/message"):
            msg = data if kind == "user/message" else dict_field(data, "message")
            text, _ = _text(msg)
            source = dict_field(msg, "source")
            if str_field(source, "kind"):
                attrs["source_kind"] = str_field(source, "kind")
            if text.strip():
                if kind == "user/message":
                    events.append(_event(ts, harness, "hook_userpromptsubmit", text, {**attrs, "tool_input": text}))
                else:
                    events.append(
                        _event(
                            ts,
                            harness,
                            "hook_assistant_response",
                            text,
                            {**attrs, "tool_response": text, "role": kind.split("/")[0]},
                        )
                    )
            else:
                events.append(_event(ts, harness, "system", kind, attrs))
        elif kind == "assistant/message":
            msg = dict_field(data, "message")
            text, reasoning = _text(msg)
            usage = _usage(data)
            if data.get("interrupted") is True:
                attrs["interrupted"] = "true"
            if reasoning.strip():
                events.append(
                    _event(ts, harness, "hook_assistant_thinking", reasoning, {**attrs, "tool_response": reasoning})
                )
            if text.strip():
                events.append(
                    _event(ts, harness, "hook_assistant_response", text, {**attrs, "tool_response": text, **usage})
                )
            elif any(key.endswith("_tokens") for key in usage):
                events.append(_event(ts, harness, "hook_token_usage", "", {**attrs, **usage}))
            elif not reasoning.strip():
                events.append(_event(ts, harness, "meta", kind, attrs))
        elif kind == "tool/call":
            call_id = str_field(data, "callId")
            name = str_field(data, "name")
            idx = len(events)
            events.append(
                _event(
                    ts,
                    harness,
                    "hook_posttooluse",
                    name,
                    {
                        **attrs,
                        "tool_name": name,
                        "tool_use_id": call_id,
                        "tool_input": str_field(data, "arguments"),
                    },
                )
            )
            if call_id:
                calls[call_id] = idx
        elif kind == "tool/result":
            msg = dict_field(data, "message")
            call_id = str_field(msg, "toolCallId")
            text, _ = _text(msg)
            error = dict_field(data, "error")
            result = {**attrs, "tool_use_id": call_id, "tool_response": text}
            if msg.get("isError") is True or error:
                result["is_error"] = "true"
            for key in ("name", "code", "reason"):
                value = str_field(error, key)
                if value:
                    result[f"error_{key}"] = value
            if "meta" in data:
                result["meta"] = json.dumps(data["meta"])
            if call_id and call_id in calls:
                existing = events[calls.pop(call_id)]
                existing["attributes"].update(result)
                existing["attributes"]["tool_result_timestamp"] = ts
            else:
                events.append(_event(ts, harness, "hook_posttooluse", call_id, result))
        elif kind == "assistant/attempt":
            failure = _attempt_failure(data)
            reason = str_field(failure, "kind")
            detail = dict_field(failure, "failure")
            if reason:
                attrs.update({"reason": reason, "error_code": str_field(detail, "code")})
                message = str_field(detail, "message")
                events.append(_event(ts, harness, "hook_error", message or reason, {**attrs, "tool_response": message}))
            else:
                events.append(_event(ts, harness, "meta", "Uncommitted assistant attempt", attrs))
        else:
            # Request headers, step boundaries, seed markers, and extension rows
            # remain visible without presenting them as new conversation messages.
            events.append(
                _event(ts, harness, row.get("event_type") or "system", kind or "Unknown session record", attrs)
            )
    return events
