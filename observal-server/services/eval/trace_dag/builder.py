# SPDX-FileCopyrightText: 2026 Swathi Saravanan <ss4522@cornell.edu>
#
# SPDX-License-Identifier: AGPL-3.0-only

"""Trace DAG builder — pure construction + thin ClickHouse fetch wrapper.

`build_trace_dag(spans)` is the unit-testable core: takes a list of span
dicts (the SpanIngest / ClickHouse row shape) and returns a TraceDAG.
`fetch_and_build(trace_id, project_id)` is the I/O wrapper that pulls
spans from ClickHouse via the existing `query_spans` and delegates.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from services.eval.trace_dag.models import (
    Confidence,
    EdgeKind,
    StateWrite,
    TraceDAG,
    TraceEdge,
    TraceNode,
)


def _to_ms(value: Any) -> int:
    if value is None:
        return 0
    if isinstance(value, (int, float)):
        # heuristic: looks like seconds vs ms
        v = float(value)
        return int(v * 1000) if v < 1e10 else int(v)
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return 0
        try:
            # ISO 8601 — accept both with and without trailing Z
            if s.endswith("Z"):
                s = s[:-1] + "+00:00"
            dt = datetime.fromisoformat(s)
            return int(dt.timestamp() * 1000)
        except ValueError:
            try:
                return _to_ms(float(s))
            except ValueError:
                return 0
    return 0


def _tuple_of_str(value: Any) -> tuple[str, ...]:
    if not value:
        return ()
    if isinstance(value, (list, tuple)):
        return tuple(v for v in value if isinstance(v, str) and v)
    return ()


def _extract_state_writes(span: dict[str, Any]) -> tuple[StateWrite, ...]:
    """Accept three shapes: list-of-dict, parallel arrays, or absent."""
    raw = span.get("state_writes")
    if isinstance(raw, list) and raw:
        out: list[StateWrite] = []
        for item in raw:
            if isinstance(item, dict):
                ns = str(item.get("namespace") or "")
                key = str(item.get("key") or "")
                vh = str(item.get("value_hash") or "")
                if ns or key:
                    out.append(StateWrite(namespace=ns, key=key, value_hash=vh))
        if out:
            return tuple(out)
    namespaces = span.get("state_write_namespaces") or []
    keys = span.get("state_write_keys") or []
    hashes = span.get("state_write_value_hashes") or []
    if not (isinstance(namespaces, list) and isinstance(keys, list) and isinstance(hashes, list)):
        return ()
    n = min(len(namespaces), len(keys), len(hashes))
    return tuple(
        StateWrite(namespace=str(namespaces[i]), key=str(keys[i]), value_hash=str(hashes[i])) for i in range(n)
    )


def _make_node(span: dict[str, Any]) -> TraceNode:
    return TraceNode(
        span_id=str(span.get("span_id") or ""),
        trace_id=str(span.get("trace_id") or ""),
        parent_span_id=(span.get("parent_span_id") or None) and str(span.get("parent_span_id")),
        name=str(span.get("name") or ""),
        method=str(span.get("method") or ""),
        type=str(span.get("type") or ""),
        start_time_ms=_to_ms(span.get("start_time")),
        end_time_ms=_to_ms(span.get("end_time")) or None,
        input=span.get("input"),
        output=span.get("output"),
        output_excerpt=span.get("output_excerpt"),
        tool_result_hash=span.get("tool_result_hash"),
        files_read=_tuple_of_str(span.get("files_read")),
        files_written=_tuple_of_str(span.get("files_written")),
        intent_label=span.get("intent_label"),
        references=_tuple_of_str(span.get("references") or span.get("span_references")),
        status=str(span.get("status") or "success"),
        state_writes=_extract_state_writes(span),
        metadata=dict(span.get("metadata") or {}),
    )


def _has_high_confidence_metadata(node: TraceNode) -> bool:
    return bool(node.files_written or node.files_read or node.output_excerpt or node.tool_result_hash)


def _infer_data_flow_edges(nodes: list[TraceNode]) -> list[TraceEdge]:
    """Output of A appears in input of B → infer edge.

    Confidence HIGH when both nodes carry `output_excerpt`/`tool_result_hash`
    metadata (the SDK Phase 1 fields). LOW when we have to fall back to
    matching raw `output`/`input` strings.
    """
    edges: list[TraceEdge] = []
    if not nodes:
        return edges
    by_start = sorted(nodes, key=lambda n: (n.start_time_ms, n.span_id))
    for i, src in enumerate(by_start):
        src_excerpt = (src.output_excerpt or src.output or "").strip()
        if not src_excerpt or len(src_excerpt) < 8:
            continue
        # use a short, distinctive needle to keep this O(n^2 * m) bounded
        needle = src_excerpt[:128]
        for dst in by_start[i + 1 :]:
            if dst.span_id == src.span_id:
                continue
            haystack = dst.input or ""
            if not haystack:
                continue
            if needle in haystack:
                conf = Confidence.HIGH if (src.output_excerpt or src.tool_result_hash) else Confidence.LOW
                edges.append(TraceEdge(src=src.span_id, dst=dst.span_id, kind=EdgeKind.DATA_FLOW, confidence=conf))
                break  # one downstream consumer is enough to record the edge
    return edges


def _infer_file_touch_edges(nodes: list[TraceNode]) -> list[TraceEdge]:
    """A writes file X then B reads file X → edge. Requires SDK Phase 1 metadata."""
    edges: list[TraceEdge] = []
    by_start = sorted(nodes, key=lambda n: (n.start_time_ms, n.span_id))
    last_write: dict[str, TraceNode] = {}
    for node in by_start:
        for f in node.files_read:
            writer = last_write.get(f)
            if writer is not None and writer.span_id != node.span_id:
                edges.append(
                    TraceEdge(
                        src=writer.span_id,
                        dst=node.span_id,
                        kind=EdgeKind.FILE_TOUCH,
                        confidence=Confidence.HIGH,
                    )
                )
        for f in node.files_written:
            last_write[f] = node
    return edges


def _parent_edges(nodes: list[TraceNode]) -> list[TraceEdge]:
    ids = {n.span_id for n in nodes}
    edges: list[TraceEdge] = []
    for n in nodes:
        if n.parent_span_id and n.parent_span_id in ids:
            edges.append(
                TraceEdge(
                    src=n.parent_span_id,
                    dst=n.span_id,
                    kind=EdgeKind.PARENT,
                    confidence=Confidence.HIGH,
                )
            )
    return edges


def build_trace_dag(spans: list[dict[str, Any]], *, trace_id: str | None = None) -> TraceDAG:
    """Pure: build a TraceDAG from a list of span dicts.

    `spans` may include rows with missing `parent_span_id` (orphans),
    duplicate `span_id`s (deduplicated by first-occurrence), or
    timestamps that don't form a tree. The DAG remains valid; derived
    edges fall back to lower-confidence kinds.
    """
    seen: set[str] = set()
    nodes: list[TraceNode] = []
    for s in spans:
        sid = str(s.get("span_id") or "")
        if not sid or sid in seen:
            continue
        seen.add(sid)
        nodes.append(_make_node(s))

    resolved_trace = trace_id or (nodes[0].trace_id if nodes else "")

    edges: list[TraceEdge] = []
    edges.extend(_parent_edges(nodes))
    edges.extend(_infer_data_flow_edges(nodes))
    edges.extend(_infer_file_touch_edges(nodes))
    return TraceDAG(trace_id=resolved_trace, nodes=nodes, edges=edges)


async def fetch_and_build(trace_id: str, project_id: str, *, limit: int = 1000) -> TraceDAG:
    """I/O wrapper: pull spans for a trace from ClickHouse and build the DAG."""
    from services.clickhouse import query_spans  # local import — avoid pulling I/O in pure path

    spans = await query_spans(project_id=project_id, trace_id=trace_id, limit=limit)
    rows = spans if isinstance(spans, list) else []
    return build_trace_dag(rows, trace_id=trace_id)
