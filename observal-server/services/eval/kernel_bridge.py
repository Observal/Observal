# SPDX-FileCopyrightText: 2026 SrihariLegend <sriharilegend23@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Observal -> Kernel bridge. Converts otel_logs hook events to kernel analysis."""

import hashlib
import json
from datetime import UTC, datetime

from services.eval.kernel import (
    ActionType,
    RawEvent,
    analyze_session,
    reconstruct_causal_edges,
)
from services.eval.kernel_scorer import score_trace

_TOOL_ACTION_MAP = {
    "read": ActionType.FILE_READ,
    "read_file": ActionType.FILE_READ,
    "write": ActionType.FILE_WRITE,
    "edit": ActionType.FILE_WRITE,
    "edit_file": ActionType.FILE_WRITE,
    "create": ActionType.FILE_WRITE,
    "shell": ActionType.BASH,
    "bash": ActionType.BASH,
    "terminal": ActionType.BASH,
    "search": ActionType.SEARCH,
    "grep": ActionType.SEARCH,
    "glob": ActionType.SEARCH,
    "find": ActionType.SEARCH,
    "think": ActionType.THINK,
    "agent": ActionType.BASH,
    "todo_list": ActionType.MCP_META,
    "todowrite": ActionType.MCP_META,
    "list_allowed_directories": ActionType.MCP_META,
    "directory_tree": ActionType.SEARCH,
    "list_directory": ActionType.SEARCH,
    "webfetch": ActionType.SEARCH,
    "websearch": ActionType.SEARCH,
    "skill": ActionType.BASH,
    "notebookedit": ActionType.FILE_WRITE,
}


def _infer_action(tool_name: str) -> ActionType:
    name = tool_name.lower().split("/")[-1]
    for key, action in _TOOL_ACTION_MAP.items():
        if key in name:
            return action
    return ActionType.BASH


def _extract_files(input_str: str) -> tuple[str, ...]:
    if not input_str:
        return ()
    try:
        params = json.loads(input_str)
        if isinstance(params, dict):
            files = []
            for key in ("file_path", "path", "filename", "file", "uri"):
                val = params.get(key)
                if val and isinstance(val, str):
                    files.append(val)
            return tuple(files)
    except (json.JSONDecodeError, TypeError):
        pass
    return ()


def _parse_ts_ms(ts_str: str) -> int:
    if not ts_str:
        return 0
    try:
        clean = ts_str.strip()
        # ISO format: 2026-04-23T16:35:14.246Z
        if "T" in clean:
            clean = clean.rstrip("Z").replace("T", " ")
        if "." in clean:
            parts = clean.split(".")
            frac = parts[1][:6]
            clean = f"{parts[0]}.{frac}"
            dt = datetime.strptime(clean, "%Y-%m-%d %H:%M:%S.%f")
        else:
            dt = datetime.strptime(clean, "%Y-%m-%d %H:%M:%S")
        dt = dt.replace(tzinfo=UTC)
        return int(dt.timestamp() * 1000)
    except (ValueError, TypeError):
        return 0


def _events_to_spans(events: list[dict]) -> list[dict]:
    """Convert raw otel_logs events into tool call spans.

    Handles three event formats:
    1. Claude Code native: tool_decision + tool_result (paired by prompt.id + tool_name)
    2. Kiro hooks: hook_pretooluse + hook_posttooluse
    3. Legacy: PreToolUse/PostToolUse in hook_event attribute
    """
    spans = []

    # --- Strategy 1: Claude Code tool_decision/tool_result ---
    decisions = []
    results = []
    hook_pre = []
    hook_post = []
    legacy_pre = []
    legacy_post = []

    for ev in events:
        event_name = ev.get("event_name", "")
        attrs = ev.get("attributes", {})
        ts = ev.get("timestamp", "")

        if event_name == "tool_decision":
            decisions.append({"attrs": attrs, "ts": ts})
        elif event_name == "tool_result":
            results.append({"attrs": attrs, "ts": ts})
        elif event_name == "hook_pretooluse":
            hook_pre.append({"attrs": attrs, "ts": ts})
        elif event_name == "hook_posttooluse":
            hook_post.append({"attrs": attrs, "ts": ts})
        else:
            hook = attrs.get("hook_event", "")
            if hook == "PreToolUse":
                legacy_pre.append({"attrs": attrs, "ts": ts})
            elif hook == "PostToolUse":
                legacy_post.append({"attrs": attrs, "ts": ts})

    # Pair tool_decision + tool_result by prompt.id + sequence proximity
    if decisions:
        result_lookup: dict[tuple[str, str], list[dict]] = {}
        for r in results:
            key = (r["attrs"].get("prompt.id", ""), r["attrs"].get("tool_name", ""))
            result_lookup.setdefault(key, []).append(r)

        for dec in decisions:
            tool = dec["attrs"].get("tool_name", "")
            prompt_id = dec["attrs"].get("prompt.id", "")
            dec_seq = int(dec["attrs"].get("event.sequence", "0") or "0")

            matched_result = None
            key = (prompt_id, tool)
            candidates = result_lookup.get(key, [])
            best_dist = float("inf")
            best_idx = -1
            for i, cand in enumerate(candidates):
                cand_seq = int(cand["attrs"].get("event.sequence", "0") or "0")
                dist = abs(cand_seq - dec_seq)
                if dist < best_dist:
                    best_dist = dist
                    best_idx = i
                    matched_result = cand

            if matched_result and best_idx >= 0:
                candidates.pop(best_idx)

            duration_ms = 0
            status = "success"
            end_ts = dec["ts"]

            if matched_result:
                duration_ms = int(matched_result["attrs"].get("duration_ms", "0") or "0")
                end_ts = matched_result["ts"]
                if matched_result["attrs"].get("success", "true") == "false":
                    status = "error"

            spans.append(
                {
                    "name": tool,
                    "start_time": dec["ts"],
                    "end_time": end_ts,
                    "input": dec["attrs"].get("tool_input", ""),
                    "output": "",
                    "latency_ms": duration_ms,
                    "status": status,
                    "prompt_id": prompt_id,
                }
            )

    # Pair hook_pretooluse + hook_posttooluse
    if hook_pre and not decisions:
        post_lookup: dict[str, list[dict]] = {}
        for hp in hook_post:
            tool = hp["attrs"].get("tool_name", "")
            post_lookup.setdefault(tool, []).append(hp)

        for pre in hook_pre:
            tool = pre["attrs"].get("tool_name", "")
            candidates = post_lookup.get(tool, [])
            matched = candidates.pop(0) if candidates else None

            if matched:
                start_ms = _parse_ts_ms(pre["ts"])
                end_ms = _parse_ts_ms(matched["ts"])
                spans.append(
                    {
                        "name": tool,
                        "start_time": pre["ts"],
                        "end_time": matched["ts"],
                        "input": pre["attrs"].get("tool_input", ""),
                        "output": matched["attrs"].get("tool_response", ""),
                        "latency_ms": max(0, end_ms - start_ms) if start_ms and end_ms else 0,
                        "status": "error" if matched["attrs"].get("tool_error") else "success",
                    }
                )
            else:
                spans.append(
                    {
                        "name": tool,
                        "start_time": pre["ts"],
                        "end_time": pre["ts"],
                        "input": pre["attrs"].get("tool_input", ""),
                        "output": "",
                        "latency_ms": 0,
                        "status": "success",
                    }
                )

    # Legacy PreToolUse/PostToolUse from hook_event attribute
    if legacy_pre and not decisions and not hook_pre:
        pending: dict[str, dict] = {}
        for pre in legacy_pre:
            tool = pre["attrs"].get("tool_name", "")
            pending[tool] = {
                "name": tool,
                "start_time": pre["ts"],
                "input": pre["attrs"].get("tool_input", ""),
                "status": "success",
            }
        for post in legacy_post:
            tool = post["attrs"].get("tool_name", "")
            pre_span = pending.pop(tool, None)
            if pre_span:
                start_ms = _parse_ts_ms(pre_span["start_time"])
                end_ms = _parse_ts_ms(post["ts"])
                pre_span["end_time"] = post["ts"]
                pre_span["output"] = post["attrs"].get("tool_response", "")
                pre_span["latency_ms"] = max(0, end_ms - start_ms) if start_ms and end_ms else 0
                if post["attrs"].get("tool_error"):
                    pre_span["status"] = "error"
                spans.append(pre_span)

    # Sort spans by start time
    spans.sort(key=lambda s: _parse_ts_ms(s.get("start_time", "")))
    return spans


def _spans_to_raw_events(spans: list[dict]) -> list[RawEvent]:
    events = []
    for idx, span in enumerate(spans):
        output = span.get("output") or ""
        result_hash = hashlib.sha256(output.encode("utf-8", errors="replace")).hexdigest()
        input_len = len(span.get("input") or "")
        output_len = len(output)
        estimated_tokens = (input_len + output_len) / 4

        prompt_id = span.get("prompt_id", "")

        events.append(
            RawEvent(
                node_id=idx,
                timestamp_ms=_parse_ts_ms(span.get("start_time", "")),
                action_type=_infer_action(span.get("name", "")),
                action_detail=span.get("input") or span.get("name") or "",
                tokens_in=0,
                tokens_out=0,
                latency_ms=span.get("latency_ms") or 0,
                result_hash=result_hash,
                files_touched=_extract_files(span.get("input")),
                cost_weight=estimated_tokens + (span.get("latency_ms", 0) * 0.1),
                output_text=output,
                trace_id=prompt_id if prompt_id else None,
            )
        )
    return events


def analyze_session_efficiency(events: list[dict]) -> dict:
    """Run kernel efficiency analysis on Observal session events from otel_logs.

    Args:
        events: List of otel_logs rows with timestamp, event_name, attributes, etc.

    Returns dict with efficiency_rating, efficiency_metrics, interpretation,
    warnings, dag (nodes + edges + stats), waste_classifications, scorer_version.
    """
    _empty = {
        "efficiency_rating": 0.0,
        "efficiency_metrics": {},
        "interpretation": {},
        "warnings": [],
        "dag": {
            "nodes": [],
            "edges": [],
            "stats": {"total_nodes": 0, "effective_nodes": 0, "reverted_nodes": 0, "waste_nodes": 0},
        },
        "waste_classifications": [],
        "scorer_version": "3.0.0",
    }

    if not events:
        _empty["warnings"] = ["No events to analyze."]
        return _empty

    spans = _events_to_spans(events)
    if not spans:
        _empty["warnings"] = ["No tool call spans found in session events."]
        return _empty

    raw_events = _spans_to_raw_events(spans)
    trace_events = reconstruct_causal_edges(raw_events)

    result = analyze_session(
        task="Agent task",
        events=trace_events,
        include_judge=False,
        span_metadata=[],
        config={"timeout_threshold_ms": 30000, "max_field_scan_length": 50000},
    )

    scores = score_trace(
        result["metrics"],
        result.get("findings", []),
        result["waste_classifications"],
    )

    # Build DAG visualization data
    events_by_id = {e.node_id: e for e in trace_events}
    effective_ids = set(result.get("effective_node_ids", []))

    # Map node_id -> span error status
    span_errors = {}
    for idx, span in enumerate(spans):
        span_errors[idx] = span.get("status") == "error"

    dag_nodes = []
    dag_edges = []
    children: dict[int, list[int]] = {}

    for nid in sorted(events_by_id):
        ev = events_by_id[nid]
        if ev.reverted_by is not None:
            status = "reverted"
        elif nid not in effective_ids:
            status = "waste"
        else:
            status = "effective"

        dag_nodes.append(
            {
                "id": nid,
                "action_type": ev.action_type.value,
                "action_detail": (ev.action_detail or "")[:120],
                "status": status,
                "error": span_errors.get(nid, False),
                "parent_ids": list(ev.parent_ids),
                "trace_id": ev.trace_id,
                "files_touched": list(ev.files_touched),
                "latency_ms": ev.latency_ms,
                "reverted_by": ev.reverted_by,
            }
        )

        for pid in ev.parent_ids:
            children.setdefault(pid, []).append(nid)
            is_cross_trace = (
                pid in events_by_id
                and events_by_id[pid].trace_id != ev.trace_id
                and ev.trace_id
                and events_by_id[pid].trace_id
            )
            dag_edges.append(
                {
                    "source": pid,
                    "target": nid,
                    "type": "cross_trace" if is_cross_trace else "causal",
                }
            )

    # Compute critical path (longest latency path through the DAG)
    dp: dict[int, float] = {}
    dp_pred: dict[int, int | None] = {}
    sorted_ids = sorted(events_by_id)
    for nid in sorted_ids:
        ev = events_by_id[nid]
        best_parent = None
        best_cost = 0.0
        for pid in ev.parent_ids:
            if pid in dp and dp[pid] > best_cost:
                best_cost = dp[pid]
                best_parent = pid
        dp[nid] = best_cost + ev.latency_ms
        dp_pred[nid] = best_parent

    critical_path: list[int] = []
    if dp:
        tail = max(dp, key=lambda k: dp[k])
        while tail is not None:
            critical_path.append(tail)
            tail = dp_pred.get(tail)
        critical_path.reverse()

    eff_count = sum(1 for n in dag_nodes if n["status"] == "effective")
    rev_count = sum(1 for n in dag_nodes if n["status"] == "reverted")
    wst_count = sum(1 for n in dag_nodes if n["status"] == "waste")

    return {
        "efficiency_rating": scores["efficiency_rating"],
        "efficiency_metrics": scores.get("efficiency_metrics", {}),
        "efficiency_detail": scores.get("efficiency_detail", {}),
        "interpretation": scores.get("interpretation", {}),
        "warnings": scores.get("warnings", []),
        "dag": {
            "nodes": dag_nodes,
            "edges": dag_edges,
            "critical_path": critical_path,
            "stats": {
                "total_nodes": len(dag_nodes),
                "effective_nodes": eff_count,
                "reverted_nodes": rev_count,
                "waste_nodes": wst_count,
            },
        },
        "waste_classifications": [
            {"category": w.get("category", "unknown"), "steps": w.get("steps", [])}
            for w in result.get("waste_classifications", [])
            if isinstance(w, dict)
        ],
        "scorer_version": scores.get("scorer_version", "3.0.0"),
    }
