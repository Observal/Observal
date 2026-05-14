# SPDX-FileCopyrightText: 2026 Swathi Saravanan <ss4522@cornell.edu>
#
# SPDX-License-Identifier: AGPL-3.0-only

"""Trace DAG — causal substrate for eval.

Pure data model. No I/O. The builder constructs one of these from spans;
the alignment / waste / longitudinal layers consume it as a read-only
graph. Edge kinds carry confidence, so consumers can degrade gracefully
when spans lack rich metadata (no `files_touched`, no `output_excerpt`).
Trace DAGs are timestamp-monotonic causal graphs; repeated action
"cycles" elsewhere refer to behavioral repetition, not graph back-edges.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum


class EdgeKind(str, Enum):
    PARENT = "parent"  # parent_id link — strongest
    DATA_FLOW = "data_flow"  # output of A appears in input of B
    FILE_TOUCH = "file_touch"  # A wrote X, B read X
    TEMPORAL = "temporal"  # only timestamp ordering — weakest


class Confidence(str, Enum):
    HIGH = "high"
    LOW = "low"


@dataclass(frozen=True)
class StateWrite:
    namespace: str
    key: str
    value_hash: str


@dataclass(frozen=True)
class TraceNode:
    span_id: str
    trace_id: str
    parent_span_id: str | None
    name: str
    method: str
    type: str
    start_time_ms: int
    end_time_ms: int | None
    input: str | None
    output: str | None
    output_excerpt: str | None
    tool_result_hash: str | None
    files_read: tuple[str, ...]
    files_written: tuple[str, ...]
    intent_label: str | None
    references: tuple[str, ...]
    status: str
    state_writes: tuple[StateWrite, ...] = ()
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class TraceEdge:
    src: str  # span_id
    dst: str  # span_id
    kind: EdgeKind
    confidence: Confidence


class TraceDAG:
    """Read-only-ish DAG built from trace spans.

    Construct via builder.build_trace_dag. After construction, consumers
    treat node and edge collections as immutable. Mutation methods are
    intentionally absent.
    """

    def __init__(self, trace_id: str, nodes: list[TraceNode], edges: list[TraceEdge]):
        self.trace_id = trace_id
        self.nodes: dict[str, TraceNode] = {n.span_id: n for n in nodes}
        self.edges: list[TraceEdge] = list(edges)
        self._children: dict[str, list[str]] = defaultdict(list)
        self._parents: dict[str, list[str]] = defaultdict(list)
        for e in self.edges:
            self._children[e.src].append(e.dst)
            self._parents[e.dst].append(e.src)

    def children(self, span_id: str) -> list[str]:
        return list(self._children.get(span_id, []))

    def parents(self, span_id: str) -> list[str]:
        return list(self._parents.get(span_id, []))

    def topo_sorted_ids(self) -> list[str]:
        """Spans sorted by start_time, stable. Cycle-safe (timestamps are total)."""
        return [n.span_id for n in sorted(self.nodes.values(), key=lambda n: (n.start_time_ms, n.span_id))]

    def confidence(self) -> Confidence:
        """Aggregate confidence — HIGH iff every derived edge is HIGH."""
        derived = [e for e in self.edges if e.kind != EdgeKind.PARENT]
        if not derived:
            return Confidence.HIGH
        return Confidence.HIGH if all(e.confidence == Confidence.HIGH for e in derived) else Confidence.LOW
