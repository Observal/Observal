# SPDX-FileCopyrightText: 2026 Swathi Saravanan <ss4522@cornell.edu>
#
# SPDX-License-Identifier: AGPL-3.0-only

"""Shared helpers for working with Trace DAG nodes."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from services.eval.trace_dag.models import TraceDAG, TraceNode


def tool_key(node: TraceNode) -> str:
    """Stable tool identity used by alignment and spec mining."""
    return (node.method or node.name or "").strip()


def spans_for_tool(dag: TraceDAG, tool_name: str) -> list[TraceNode]:
    """Return trace nodes whose method/name matches a tool name."""
    target = tool_name.strip()
    return [dag.nodes[sid] for sid in dag.topo_sorted_ids() if tool_key(dag.nodes[sid]) == target]
