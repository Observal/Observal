# SPDX-FileCopyrightText: 2026 Swathi Saravanan <ss4522@cornell.edu>
#
# SPDX-License-Identifier: AGPL-3.0-only

"""Pure evaluators for OutcomeCheck — no I/O, no LLM, no DB.

Every public function takes ``(trace_dag, params)`` and returns
``(passed: bool, meta: dict)``. The meta carries evidence span ids and
reasoning for the reasoning layer to consume; it never carries a score.
"""

from __future__ import annotations

import fnmatch
import json
import re
from typing import TYPE_CHECKING, Any

from services.eval.spec_dag.models import OutcomeCheck, OutcomeCheckType
from services.eval.trace_dag.helpers import spans_for_tool

if TYPE_CHECKING:
    from services.eval.trace_dag.models import TraceDAG, TraceNode


# ── helpers ──


def _final_user_facing(dag: TraceDAG) -> TraceNode | None:
    """The last span that emitted text for the end user.

    Heuristic order: explicit ``user_facing=true`` metadata; span type in
    ``{"agent_to_user", "assistant_response", "final_response"}``; otherwise
    the last span by start_time with non-empty output.
    """
    nodes_sorted = [dag.nodes[i] for i in dag.topo_sorted_ids()]
    for node in reversed(nodes_sorted):
        if node.metadata.get("user_facing") in (True, "true", "True", "1"):
            return node
    user_types = {"agent_to_user", "assistant_response", "final_response"}
    for node in reversed(nodes_sorted):
        if node.type in user_types:
            return node
    for node in reversed(nodes_sorted):
        if node.output or node.output_excerpt:
            return node
    return None


def _input_dict(node: TraceNode) -> dict[str, Any]:
    if not node.input:
        return {}
    try:
        v = json.loads(node.input)
    except (json.JSONDecodeError, TypeError, ValueError):
        return {}
    return v if isinstance(v, dict) else {}


def _output_text(node: TraceNode) -> str:
    return (node.output_excerpt or node.output or "") or ""


def _match_text(pattern: str, text: str, match_type: str, threshold: float = 0.85) -> tuple[bool, dict[str, Any]]:
    if not text:
        return False, {"reason": "empty target text"}
    if match_type == "exact":
        return text == pattern, {"match_type": "exact"}
    if match_type == "substring":
        return pattern in text, {"match_type": "substring"}
    if match_type == "regex":
        try:
            return re.search(pattern, text) is not None, {"match_type": "regex"}
        except re.error as e:
            return False, {"reason": f"invalid regex: {e}"}
    if match_type == "semantic":
        # Real cosine via the pluggable embedding provider. Default is a
        # deterministic hashed-token bag-of-words; OpenAI-compatible
        # providers plug in via EMBEDDING_MODEL_* env vars.
        from services.eval.embeddings import get_provider, semantic_score

        provider = get_provider()
        score = semantic_score(pattern, text, provider=provider)
        return score >= threshold, {
            "match_type": "semantic",
            "cosine": score,
            "threshold": threshold,
            "provider": provider.name,
        }
    return False, {"reason": f"unknown match_type {match_type!r}"}


# ── individual evaluators ──


def check_response_contains(dag: TraceDAG, params: dict) -> tuple[bool, dict]:
    pattern = params.get("pattern", "")
    match_type = params.get("match_type", "substring")
    threshold = float(params.get("threshold", 0.85))

    final = _final_user_facing(dag)
    if final is None:
        return False, {"reason": "no final user-facing span"}
    text = _output_text(final)
    passed, meta = _match_text(pattern, text, match_type, threshold)
    meta.update({"matched_span_id": final.span_id, "pattern": pattern})
    return passed, meta


def check_response_schema(dag: TraceDAG, params: dict) -> tuple[bool, dict]:
    schema = params.get("schema") or {}
    final = _final_user_facing(dag)
    if final is None:
        return False, {"reason": "no final user-facing span"}
    text = _output_text(final)
    try:
        parsed = json.loads(text)
    except (json.JSONDecodeError, ValueError) as e:
        return False, {"reason": f"final response is not JSON: {e}", "matched_span_id": final.span_id}
    try:
        import jsonschema  # optional dep; fail closed if absent

        jsonschema.validate(parsed, schema)
        return True, {"matched_span_id": final.span_id}
    except ImportError:
        # Fallback minimal validator: top-level required + type check
        ok, why = _minimal_schema_check(parsed, schema)
        return ok, {"matched_span_id": final.span_id, "reason": why or "minimal_schema_pass"}
    except Exception as e:
        return False, {"matched_span_id": final.span_id, "reason": str(e)}


def _minimal_schema_check(value: Any, schema: dict) -> tuple[bool, str | None]:
    expected = schema.get("type")
    if expected == "object" and not isinstance(value, dict):
        return False, "expected object"
    if expected == "array" and not isinstance(value, list):
        return False, "expected array"
    for required_key in schema.get("required", []) or []:
        if not isinstance(value, dict) or required_key not in value:
            return False, f"missing required key {required_key!r}"
    return True, None


def _hash_value(value: Any) -> str:
    """Mirror of services.span_enrichment.hash_state_value (avoids cycle)."""
    import hashlib

    try:
        canonical = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        canonical = str(value)
    return hashlib.sha256(canonical.encode("utf-8", errors="replace")).hexdigest()


def _state_writes_matching(dag: TraceDAG, namespace: str, key: str) -> list[tuple[str, str, int]]:
    """Return [(span_id, value_hash, start_time_ms), ...] in trace order."""
    out: list[tuple[str, str, int]] = []
    for sid in dag.topo_sorted_ids():
        node = dag.nodes[sid]
        for sw in node.state_writes:
            if sw.namespace == namespace and sw.key == key:
                out.append((sid, sw.value_hash, node.start_time_ms))
    return out


def _scan_state_in_outputs(dag: TraceDAG, namespace: str, key: str, expected: Any) -> tuple[bool, str | None]:
    """Output-scan fallback used when no state_writes are present.

    Conservative: requires the expected value to appear as a substring of a
    span's output, plus the namespace.key marker — to avoid matching random
    text. (Imperfect by design; this is the fallback path.)
    """
    if expected is None:
        return False, None
    needle_value = str(expected)
    if not needle_value:
        return False, None
    marker = f"{namespace}.{key}"
    for sid in dag.topo_sorted_ids():
        text = _output_text(dag.nodes[sid])
        if not text:
            continue
        if needle_value in text and (marker in text or namespace in text):
            return True, sid
    return False, None


def check_state_equals(dag: TraceDAG, params: dict) -> tuple[bool, dict]:
    """Primary path: state_writes. Fallback: scan tool outputs."""
    namespace = params.get("namespace", "")
    key = params.get("key", "")
    expected = params.get("expected_value")
    expected_hash = _hash_value(expected)

    writes = _state_writes_matching(dag, namespace, key)
    if writes:
        # Take the LAST write per (ns,key) as the trace-end value
        last_sid, last_hash, _ = writes[-1]
        if last_hash == expected_hash:
            return True, {
                "matched_span_id": last_sid,
                "namespace": namespace,
                "key": key,
                "source": "state_writes",
                "value_hash": last_hash,
            }
        return False, {
            "reason": "state not equal",
            "namespace": namespace,
            "key": key,
            "expected_hash": expected_hash,
            "observed_hash": last_hash,
            "source": "state_writes",
            "matched_span_id": last_sid,
        }

    # Fallback to output scanning
    passed, sid = _scan_state_in_outputs(dag, namespace, key, expected)
    if not passed:
        return False, {
            "reason": "state not observable",
            "namespace": namespace,
            "key": key,
            "source": "output_scan_fallback",
        }
    return True, {
        "matched_span_id": sid,
        "namespace": namespace,
        "key": key,
        "source": "output_scan_fallback",
    }


def check_state_changed(dag: TraceDAG, params: dict) -> tuple[bool, dict]:
    """Primary path: ordered state_writes for namespace+key. Fallback: output scan."""
    namespace = params.get("namespace", "")
    key = params.get("key", "")
    from_value = params.get("from_value")
    to_value = params.get("to_value")
    from_hash = _hash_value(from_value)
    to_hash = _hash_value(to_value)

    writes = _state_writes_matching(dag, namespace, key)
    if writes:
        # Earliest from_hash and a later to_hash
        first_from_idx = next((i for i, (_, h, _) in enumerate(writes) if h == from_hash), None)
        if first_from_idx is None:
            # to-only case: latest write equals to_hash with no observed from
            if writes[-1][1] == to_hash:
                return True, {
                    "namespace": namespace,
                    "key": key,
                    "to_span": writes[-1][0],
                    "source": "state_writes",
                    "note": "from_value not observed",
                }
            return False, {
                "reason": "from_value not observed",
                "namespace": namespace,
                "key": key,
                "source": "state_writes",
            }
        for j in range(first_from_idx + 1, len(writes)):
            if writes[j][1] == to_hash:
                return True, {
                    "namespace": namespace,
                    "key": key,
                    "from_span": writes[first_from_idx][0],
                    "to_span": writes[j][0],
                    "source": "state_writes",
                }
        return False, {
            "reason": "to_value did not follow from_value",
            "namespace": namespace,
            "key": key,
            "source": "state_writes",
        }

    # Fallback
    saw_from, sid_from = _scan_state_in_outputs(dag, namespace, key, from_value)
    saw_to, sid_to = _scan_state_in_outputs(dag, namespace, key, to_value)
    if saw_from and saw_to and sid_from and sid_to:
        ts_from = dag.nodes[sid_from].start_time_ms
        ts_to = dag.nodes[sid_to].start_time_ms
        if ts_to >= ts_from:
            return True, {
                "namespace": namespace,
                "key": key,
                "from_span": sid_from,
                "to_span": sid_to,
                "source": "output_scan_fallback",
            }
        return False, {"reason": "to_value observed before from_value", "source": "output_scan_fallback"}
    if saw_to and not saw_from:
        return True, {
            "namespace": namespace,
            "key": key,
            "to_span": sid_to,
            "source": "output_scan_fallback",
            "note": "from_value not observed",
        }
    return False, {
        "reason": "state change not observable",
        "namespace": namespace,
        "key": key,
        "source": "output_scan_fallback",
    }


def _params_match_loose(actual: dict[str, Any], constraints: dict[str, Any]) -> bool:
    """Constraints are *loose*: only checks listed keys, ignores the rest."""
    for k, expected in constraints.items():
        if k not in actual:
            return False
        if actual[k] != expected:
            return False
    return True


def check_tool_was_called(dag: TraceDAG, params: dict) -> tuple[bool, dict]:
    tool = params.get("tool_name", "")
    min_count = int(params.get("min_count", 1))
    constraints = params.get("param_constraints") or None

    spans = spans_for_tool(dag, tool)
    matching: list[str] = []
    for s in spans:
        if constraints is None:
            matching.append(s.span_id)
            continue
        if _params_match_loose(_input_dict(s), constraints):
            matching.append(s.span_id)
    passed = len(matching) >= min_count
    return passed, {
        "tool": tool,
        "count": len(matching),
        "min_count": min_count,
        "matching_spans": matching,
        "param_constraints": constraints or {},
    }


def check_tool_result_contains(dag: TraceDAG, params: dict) -> tuple[bool, dict]:
    tool = params.get("tool_name", "")
    pattern = params.get("pattern", "")
    match_type = params.get("match_type", "substring")
    spans = spans_for_tool(dag, tool)
    if not spans:
        return False, {"reason": f"no spans matching tool {tool!r}"}
    for s in spans:
        passed, meta = _match_text(pattern, _output_text(s), match_type)
        if passed:
            meta.update({"matched_span_id": s.span_id, "tool": tool, "pattern": pattern})
            return True, meta
    return False, {"tool": tool, "pattern": pattern, "match_type": match_type, "reason": "no matching output"}


def _path_matches(pattern: str, path: str) -> bool:
    if any(ch in pattern for ch in "*?["):
        return fnmatch.fnmatch(path, pattern)
    try:
        return re.fullmatch(pattern, path) is not None
    except re.error:
        return path == pattern


def check_artifact_exists(dag: TraceDAG, params: dict) -> tuple[bool, dict]:
    path_pattern = params.get("path_pattern", "")
    content_pattern = params.get("content_pattern")
    matches: list[tuple[str, str]] = []
    for sid in dag.topo_sorted_ids():
        node = dag.nodes[sid]
        for path in node.files_written:
            if _path_matches(path_pattern, path):
                matches.append((sid, path))
    if not matches:
        return False, {"reason": "no files_written matching pattern", "path_pattern": path_pattern}
    if content_pattern is None:
        sid, path = matches[0]
        return True, {"matched_span_id": sid, "path": path}
    for sid, path in matches:
        text = _output_text(dag.nodes[sid])
        if content_pattern in text:
            return True, {"matched_span_id": sid, "path": path, "content_match": True}
    sid, path = matches[0]
    return False, {"matched_span_id": sid, "path": path, "reason": "content_pattern did not match"}


def check_custom_python(dag: TraceDAG, params: dict) -> tuple[bool, dict]:
    """Fail closed: arbitrary Python checks are not executed in-process."""
    fn_path = str(params.get("function_path") or "")
    description = str(params.get("description") or "")
    if not fn_path:
        return False, {"reason": "function_path missing"}
    return False, {
        "reason": "custom_python checks are disabled; use built-in deterministic check types",
        "function_path": fn_path,
        "description": description,
    }


# ── dispatch ──


_DISPATCH = {
    OutcomeCheckType.RESPONSE_CONTAINS: check_response_contains,
    OutcomeCheckType.RESPONSE_SCHEMA: check_response_schema,
    OutcomeCheckType.STATE_EQUALS: check_state_equals,
    OutcomeCheckType.STATE_CHANGED: check_state_changed,
    OutcomeCheckType.TOOL_WAS_CALLED: check_tool_was_called,
    OutcomeCheckType.TOOL_RESULT_CONTAINS: check_tool_result_contains,
    OutcomeCheckType.ARTIFACT_EXISTS: check_artifact_exists,
    OutcomeCheckType.CUSTOM_PYTHON: check_custom_python,
}


def evaluate_outcome_check(check: OutcomeCheck, dag: TraceDAG) -> tuple[bool, dict]:
    """Dispatch to the per-check evaluator. Pure, deterministic."""
    fn = _DISPATCH.get(check.check_type)
    if fn is None:
        return False, {"reason": f"unknown check_type {check.check_type!r}"}
    return fn(dag, dict(check.params or {}))
