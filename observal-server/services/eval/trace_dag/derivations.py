# SPDX-FileCopyrightText: 2026 Swathi Saravanan <ss4522@cornell.edu>
#
# SPDX-License-Identifier: AGPL-3.0-only

"""Derivations over a TraceDAG — reverts, clusters, effective nodes, intent.

Pure functions. All take a TraceDAG, return data structures or sets/lists.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from services.eval.trace_dag.models import TraceDAG, TraceNode

WRITE_TYPES = {"file_write", "file_delete"}


@dataclass(frozen=True)
class RevertPair:
    earlier: str  # span_id whose work was undone
    later: str  # span_id that undid it
    file: str | None
    method: str  # "hash_match" | "file_overwrite"


@dataclass(frozen=True)
class WriteCluster:
    cluster_id: str
    span_ids: tuple[str, ...]
    intent_label: str | None


def _is_file_write(node: TraceNode) -> bool:
    if node.files_written:
        return True
    if node.method.lower() in {"write", "edit", "notebookedit", "edit_file", "create"}:
        return True
    return node.name in {"Write", "Edit", "NotebookEdit"}


def _is_file_read(node: TraceNode) -> bool:
    if node.files_read:
        return True
    if node.method.lower() in {"read", "read_file"}:
        return True
    return node.name == "Read"


def find_reverts(dag: TraceDAG) -> list[RevertPair]:
    """Pairs (earlier, later) where `later` semantically undoes `earlier`.

    Two detection strategies:
    1. **Hash match** — same file path, identical `tool_result_hash` at later
       span as at an earlier span before an intermediate write to that file.
       (i.e. a third write restored the file to its earlier state.)
    2. **File overwrite** — multiple writes to the same path; all writes
       between the first and the last are candidate reverts of the previous
       writer's state.
    """
    pairs: list[RevertPair] = []
    by_start = sorted(dag.nodes.values(), key=lambda n: (n.start_time_ms, n.span_id))

    # Hash-match strategy: per file, sequence of (span, hash) for nodes touching it.
    file_hash_seq: dict[str, list[tuple[str, str | None]]] = defaultdict(list)
    file_writers: dict[str, list[str]] = defaultdict(list)
    for node in by_start:
        touched = set(node.files_written) | set(node.files_read)
        if _is_file_write(node):
            for f in node.files_written or touched:
                file_writers[f].append(node.span_id)
                file_hash_seq[f].append((node.span_id, node.tool_result_hash))
        elif node.tool_result_hash and node.files_read:
            for f in node.files_read:
                file_hash_seq[f].append((node.span_id, node.tool_result_hash))

    for path, seq in file_hash_seq.items():
        seen: dict[str, int] = {}
        for idx, (sid, h) in enumerate(seq):
            if h is None:
                continue
            if h in seen and idx - seen[h] >= 2:
                # everything strictly between seen[h] and idx was undone
                for k in range(seen[h] + 1, idx):
                    pairs.append(
                        RevertPair(
                            earlier=seq[k][0],
                            later=sid,
                            file=path,
                            method="hash_match",
                        )
                    )
            seen[h] = idx

    # File-overwrite strategy: chain of writes to same file. Each writer except the
    # last is reverted by the next writer when no terminal hash equality is observed.
    for path, writers in file_writers.items():
        if len(writers) < 2:
            continue
        # if hash_match already covered this path, skip (avoid duplicates)
        already = {(p.earlier, p.later) for p in pairs if p.file == path}
        for i in range(len(writers) - 1):
            pair = (writers[i], writers[i + 1])
            if pair in already:
                continue
            pairs.append(
                RevertPair(
                    earlier=writers[i],
                    later=writers[i + 1],
                    file=path,
                    method="file_overwrite",
                )
            )
            already.add(pair)

    return pairs


def cluster_writes(dag: TraceDAG) -> list[WriteCluster]:
    """Union-find clustering of write spans by shared parent and intent ancestor."""
    write_ids = [nid for nid, n in dag.nodes.items() if _is_file_write(n)]
    if not write_ids:
        return []

    parent: dict[str, str] = {nid: nid for nid in write_ids}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            if ra > rb:
                ra, rb = rb, ra
            parent[rb] = ra

    # share parent_span_id
    by_parent: dict[str, list[str]] = defaultdict(list)
    for nid in write_ids:
        n = dag.nodes[nid]
        if n.parent_span_id:
            by_parent[n.parent_span_id].append(nid)
    for siblings in by_parent.values():
        for i in range(1, len(siblings)):
            union(siblings[0], siblings[i])

    # share intent ancestor
    by_intent: dict[str, list[str]] = defaultdict(list)
    for nid in write_ids:
        anc = intent_ancestor(dag, nid)
        if anc:
            anc_label = dag.nodes[anc].intent_label or anc
            by_intent[anc_label].append(nid)
    for group in by_intent.values():
        for i in range(1, len(group)):
            union(group[0], group[i])

    groups: dict[str, list[str]] = defaultdict(list)
    for nid in write_ids:
        groups[find(nid)].append(nid)

    out: list[WriteCluster] = []
    for cid, members in groups.items():
        sorted_members = tuple(sorted(members, key=lambda x: (dag.nodes[x].start_time_ms, x)))
        intent = dag.nodes[cid].intent_label
        out.append(WriteCluster(cluster_id=cid, span_ids=sorted_members, intent_label=intent))
    return out


def effective_nodes(dag: TraceDAG) -> set[str]:
    """Span ids whose work survived to the final output.

    A node is effective unless:
    - it's a write that was reverted by a later write to the same file, or
    - it's a duplicate file_read of the same content (same hash) as an
      earlier read in the trace.
    """
    reverts = find_reverts(dag)
    reverted: set[str] = {p.earlier for p in reverts}

    effective: set[str] = set()
    seen_reads: set[tuple[str, str]] = set()  # (file, hash)
    for nid in dag.topo_sorted_ids():
        node = dag.nodes[nid]
        if nid in reverted:
            continue
        if _is_file_read(node) and node.tool_result_hash:
            for f in node.files_read or ("",):
                key = (f, node.tool_result_hash)
                if key in seen_reads:
                    break
                seen_reads.add(key)
            else:
                effective.add(nid)
                continue
            # broke out → duplicate read
            continue
        effective.add(nid)
    return effective


def intent_ancestor(dag: TraceDAG, span_id: str) -> str | None:
    """Highest ancestor whose tool call expressed the goal this span serves.

    Walks up parent edges; returns the topmost ancestor that has a
    non-empty `intent_label`. Falls back to the root parent if no
    ancestor labels are present.
    """
    if span_id not in dag.nodes:
        return None
    current = span_id
    last_with_label: str | None = None
    visited: set[str] = set()
    while True:
        if current in visited:
            break
        visited.add(current)
        node = dag.nodes.get(current)
        if node is None:
            break
        if node.intent_label:
            last_with_label = current
        if not node.parent_span_id or node.parent_span_id not in dag.nodes:
            break
        current = node.parent_span_id
    if last_with_label:
        return last_with_label
    # fall back to root
    return current if current != span_id else None


def find_redundant_reads(dag: TraceDAG) -> list[tuple[str, str]]:
    """Pairs (earlier_read, later_read) where the later read fetched identical data.

    Defined as: same file path AND same `tool_result_hash`, both reads in
    the same intent cluster (or both with no intent ancestor — global).
    """
    reads: list[tuple[str, TraceNode]] = []
    for nid in dag.topo_sorted_ids():
        node = dag.nodes[nid]
        if _is_file_read(node) and node.tool_result_hash:
            reads.append((nid, node))
    out: list[tuple[str, str]] = []
    seen: dict[tuple[str | None, str, str], str] = {}
    for nid, node in reads:
        anc = intent_ancestor(dag, nid)
        for f in node.files_read or ("",):
            key = (anc, f, node.tool_result_hash or "")
            if key in seen:
                out.append((seen[key], nid))
            else:
                seen[key] = nid
    return out
