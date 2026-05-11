# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-FileCopyrightText: 2026 SrihariLegend <sriharilegend23@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""
Agent Observability Kernel — Proof of Concept (v4.4)
=====================================================

A calculation engine for agent coding sessions. Produces objective measurements
from trace data. Does NOT produce evaluative judgments (grades, "good/bad").
For interpretation, use kernel_scorer.py or implement your own scorer.

Changelog (latest first):

v4.4: Span-level detection — tool error/timeout/duplicate counts, ignored
      failure and retry pair detection, adversarial content scanning.
      New analyze_session() params: span_metadata, config.
      New return keys: findings, data_quality.
v4.3: PER cycle exclusion — get_effective_nodes() strips repeated cycle
      iterations. PER now penalizes non-revert waste (stuck loops).
v4.2: _is_code_identifier() filter prevents false causal edges from English words.
v4.1: _action_key() replaces truncation. Configurable waste thresholds.
v4:   Causal reconstruction engine, multi-language hashing, target-aware
      entropy, deterministic waste classifier, repetition cycle detector,
      enhanced bash mutation detector.

See BRAIN.md for full v1-v4.3 changelog.

No external dependencies. Pure Python 3.11.
"""

from __future__ import annotations

import ast
import hashlib
import json
import math
import os
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from enum import Enum

# ---------------------------------------------------------------------------
# Detection configuration defaults
# ---------------------------------------------------------------------------

DEFAULT_CONFIG = {
    "timeout_threshold_ms": 30000,
    "max_field_scan_length": 50000,
    "retry_lookahead_window": 5,
    "max_retry_distance": 10,
    "secret_patterns": ["SECRET_KEY", "API_KEY", "OPENAI_API_KEY"],
}

# Adversarial detection patterns (compiled once, thread-safe)
_HTML_COMMENT_EVAL_RE = re.compile(
    r"<!--.*?(EVALUATION|SCORE|JUDGE|RATING|OVERRIDE|ASSESSMENT|INSTRUCTION).*?-->", re.IGNORECASE | re.DOTALL
)
_SYSTEM_PROMPT_RE = re.compile(
    r"(You are a (judge|evaluator|scorer)|Score this as|SYSTEM:|INSTRUCTION:)", re.IGNORECASE
)

# Score assertion detection: exact-match on narrowed key set (Req 5)
_EVAL_JSON_KEYS = frozenset(
    [
        "overall_score",
        "final_score",
        "assessment_score",
        "composite_score",
        "efficiency_rating",
    ]
)

_ZERO_WIDTH_RE = re.compile(r"[​‌‍﻿⁠]{6,}")


# ---------------------------------------------------------------------------
# 1. Trace Event Schema
# ---------------------------------------------------------------------------


class ActionType(Enum):
    FILE_READ = "file_read"
    FILE_WRITE = "file_write"
    FILE_DELETE = "file_delete"
    BASH = "bash"
    SEARCH = "search"
    THINK = "think"
    MCP_META = "mcp_meta"  # protocol overhead: tool_list, resource_list, initialize, ping, etc.


class TaskComplexity(Enum):
    TARGETED_FIX = "targeted_fix"
    EXPLORATION = "exploration"
    GREENFIELD = "greenfield"


@dataclass
class TraceEvent:
    node_id: int
    parent_ids: list[int]
    timestamp_ms: int
    action_type: ActionType
    action_detail: str
    tokens_in: int
    tokens_out: int
    latency_ms: int
    result_hash: str
    files_touched: tuple[str, ...] = ()
    reverted_by: int | None = None
    changeset_id: int | None = None
    cost_weight: float | None = None  # override for token cost modeling
    trace_id: str | None = None  # originating trace for session-level analysis
    output_text: str = ""


# ---------------------------------------------------------------------------
# 1.5 Reference AST Normalizer
# ---------------------------------------------------------------------------


def normalize_python_hash(source: str) -> str:
    """
    Semantic hash for Python source. Parses to AST, dumps canonical form,
    hashes the dump. Whitespace, comments, formatting differences produce
    the same hash. Falls back to whitespace-normalized hash on SyntaxError.
    """
    try:
        tree = ast.parse(source)
        canonical = ast.dump(tree, annotate_fields=True)
        return hashlib.sha256(canonical.encode()).hexdigest()
    except SyntaxError:
        normalized = re.sub(r"\s+", " ", source.strip())
        return hashlib.sha256(normalized.encode()).hexdigest()


# ---------------------------------------------------------------------------
# 1.6 Bash Mutation Detector
# ---------------------------------------------------------------------------

_BASH_MUTATION_RE = re.compile(
    r"(?:sed\s+-i|tee\s|echo\s.*>>?|cat\s.*>\s|mv\s|cp\s|"
    r"git\s+checkout|git\s+reset|git\s+restore|chmod\s|chown\s|"
    r"rm\s|mkdir\s|touch\s|patch\s|curl\s.*-o|wget\s|"
    r"python[23]?\s+-c\s.*(?:open|write)\s*\(|perl\s+-[ip]e?\s|awk\s.*>\s|"
    r"ruby\s+-e\s.*(?:File\.|IO\.|open)|"
    r"node\s+-e\s.*(?:fs\.|writeFile)|"
    r"go\s+run\s|"
    r">\s*\S+|"  # bare redirect: > file
    r"\|\s*tee\s|"  # pipe to tee
    r"install\s|"  # npm install, pip install, etc.
    r"jq\s.*>\s|"  # jq ... > file
    r"ffmpeg\s|sox\s|convert\s|"  # media tools with output files
    r"tar\s.*-[xf]|unzip\s|gunzip\s|"  # archive extraction
    r"go\s+mod\s+tidy|cargo\s+build|npm\s+install|pip\s+install|"
    r"make\b|cmake\b|ninja\b|"  # build systems
    r"dd\s)"  # dd
)


def detect_bash_mutations(command: str) -> list[str]:
    """
    Heuristic: scan a bash command for patterns that likely mutate files
    without a FILE_WRITE event. Returns list of warning strings.
    """
    if _BASH_MUTATION_RE.search(command):
        return [f"Potential untracked file mutation: {command[:120]}"]
    return []


_SHELL_ERROR_RE = re.compile(
    r"(?:"
    r"Failed to compile|"
    r"SyntaxError|TypeError|ReferenceError|ImportError|ModuleNotFoundError|"
    r"NameError|AttributeError|KeyError|ValueError|RuntimeError|"
    r"Module not found|Cannot find module|"
    r"npm ERR!|"
    r"ENOENT|EACCES|EPERM|"
    r"command not found|"
    r"No such file or directory|"
    r"Permission denied|"
    r"Traceback \(most recent call last\)|"
    r"FAILED|"
    r"panic:|"
    r"error\[E\d+\]|"
    r"BUILD FAILED|"
    r"exit code [1-9]\d*|"
    r"returned non-zero exit status"
    r")"
)

_PACKAGE_INSTALL_RE = re.compile(
    r"(?:npm\s+install|npm\s+i|yarn\s+add|pip\s+install|pip3\s+install|"
    r"pipenv\s+install|poetry\s+add|cargo\s+add|go\s+get)\s+(.+)",
    re.IGNORECASE,
)

_VERIFY_COMMAND_RE = re.compile(
    r"(?:pytest|jest|mocha|vitest|npm\s+test|npm\s+run|yarn\s+test|"
    r"cargo\s+test|go\s+test|make\s+test|python\s+-m\s+pytest|"
    r"node\s|npx\s|tsc|eslint|flake8|mypy|"
    r"npm\s+start|npm\s+run\s+dev|npm\s+run\s+build|npm\s+create|"
    r"cargo\s+build|cargo\s+check|go\s+build|make\b|cmake\b|"
    r"Start-Process\b|Invoke-Expression\b|& npm\b|& node\b|"
    r"python\s|python3\s|ruby\s|java\s|javac\s|gcc\s|g\+\+\s)",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# 1.7 Multi-Language Semantic Hasher
# ---------------------------------------------------------------------------


def _detect_language(path: str, content: str) -> str:
    """Heuristic language detection from file extension or content."""
    ext = path.rsplit(".", 1)[-1].lower() if "." in path else ""
    _map = {
        "py": "python",
        "json": "json",
        "yaml": "yaml",
        "yml": "yaml",
        "toml": "toml",
        "md": "markdown",
        "css": "css",
        "js": "javascript",
        "ts": "typescript",
        "jsx": "javascript",
        "tsx": "typescript",
        "go": "go",
        "rs": "rust",
        "rb": "ruby",
        "java": "java",
        "c": "c",
        "cpp": "cpp",
        "h": "c",
        "hpp": "cpp",
        "sql": "sql",
        "sh": "shell",
        "bash": "shell",
    }
    return _map.get(ext, "unknown")


def normalize_json_hash(content: str) -> str:
    """Semantic hash for JSON: parse, sort keys, re-serialize canonically."""
    try:
        obj = json.loads(content)
        canonical = json.dumps(obj, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode()).hexdigest()
    except (json.JSONDecodeError, TypeError):
        return _normalize_whitespace_hash(content)


def _normalize_whitespace_hash(content: str) -> str:
    """Fallback: collapse all whitespace, hash."""
    normalized = re.sub(r"\s+", " ", content.strip())
    return hashlib.sha256(normalized.encode()).hexdigest()


def semantic_hash(content: str, file_path: str = "") -> str:
    """
    Dispatch to the best available normalizer based on detected language.
    Python → AST normalizer. JSON → key-sorted canonical. Others → whitespace.
    """
    lang = _detect_language(file_path, content)
    if lang == "python":
        return normalize_python_hash(content)
    elif lang == "json":
        return normalize_json_hash(content)
    else:
        return _normalize_whitespace_hash(content)


# ---------------------------------------------------------------------------
# 1.8 Causal Reconstruction Engine
# ---------------------------------------------------------------------------


@dataclass
class RawEvent:
    """
    A trace event WITHOUT parent_ids. This is what real agent frameworks emit.
    The causal reconstruction engine infers parent_ids from these.
    """

    node_id: int
    timestamp_ms: int
    action_type: ActionType
    action_detail: str
    tokens_in: int
    tokens_out: int
    latency_ms: int
    result_hash: str
    files_touched: tuple[str, ...] = ()
    cost_weight: float | None = None
    output_text: str = ""  # captured stdout/stderr for BASH, or content for reads
    trace_id: str | None = None  # groups events by originating trace for per-trace breakdowns


def _is_code_identifier(token: str) -> bool:
    """
    Returns True if token looks like a code identifier rather than a plain
    English word. Code identifiers contain at least one of: / . _ - digit,
    or have mixed case (camelCase/PascalCase).
    Filters out: "Error", "Expected", "True", "False", "line", "test", etc.
    Keeps: "utils.py", "internal/auth", "my_module", "setUp", "line42", etc.
    """
    if any(c in token for c in "/._-:"):
        return True
    if any(c.isdigit() for c in token):
        return True
    has_upper = any(c.isupper() for c in token[1:])  # mixed case after first char
    has_lower = any(c.islower() for c in token)
    return bool(has_upper and has_lower)


def reconstruct_causal_edges(raw_events: list[RawEvent], max_lookback: int = 20) -> list[TraceEvent]:
    """
    Infer parent_ids from raw events using three heuristics:

    1. DATA-FLOW: If event B reads/touches file F, and event A was the most
       recent write to F, then A → B.
    2. TEMPORAL RECENCY: If no data-flow parent is found, the immediately
       preceding event is the parent (sequential fallback).
    3. OUTPUT-REFERENCE: If event B's action_detail contains a substring
       that appeared in event A's output_text (file paths, error messages),
       then A → B.

    This produces a DAG that approximates true causal structure from
    observable signals alone — no agent internals needed.
    """
    sorted_events = sorted(raw_events, key=lambda e: (e.timestamp_ms, e.node_id))
    # Track last writer per file
    last_writer: dict[str, int] = {}
    # Track output text index for reference matching
    output_index: dict[int, str] = {}
    # Track file paths mentioned in outputs

    result: list[TraceEvent] = []

    for idx, raw in enumerate(sorted_events):
        parents: set[int] = set()

        # Heuristic 1: DATA-FLOW — file read/write depends on last writer
        for f in raw.files_touched:
            if f in last_writer:
                parents.add(last_writer[f])

        # Heuristic 2: BASH that mentions a file depends on last writer
        if raw.action_type == ActionType.BASH:
            for f, writer_id in last_writer.items():
                if f in raw.action_detail:
                    parents.add(writer_id)

        # Heuristic 3: OUTPUT-REFERENCE — scan recent outputs for references
        if raw.action_detail and idx > 0:
            lookback_start = max(0, idx - max_lookback)
            for prev_idx in range(lookback_start, idx):
                prev = sorted_events[prev_idx]
                prev_out = prev.output_text
                if not prev_out:
                    continue
                # Check if current action references content from prev output
                # Extract identifiers: file paths, package names, symbols (>=4 chars)
                # Filter: must look like a code identifier (contains / . _ - digit
                # or mixed case) to avoid matching plain English words like "Error"
                detail_tokens = re.findall(r"[\w./\-]{4,}", raw.action_detail)
                for token in detail_tokens:
                    if not _is_code_identifier(token):
                        continue
                    if token in prev_out:
                        parents.add(prev.node_id)
                        break

        # Heuristic 4: TEMPORAL FALLBACK — if no causal parent found,
        # link to immediately preceding event
        if not parents and idx > 0:
            parents.add(sorted_events[idx - 1].node_id)

        # Update file state
        if raw.action_type in (ActionType.FILE_WRITE, ActionType.FILE_DELETE):
            for f in raw.files_touched:
                last_writer[f] = raw.node_id

        # Store output for future reference matching
        if raw.output_text:
            output_index[raw.node_id] = raw.output_text

        ev = TraceEvent(
            node_id=raw.node_id,
            parent_ids=sorted(parents),
            timestamp_ms=raw.timestamp_ms,
            action_type=raw.action_type,
            action_detail=raw.action_detail,
            tokens_in=raw.tokens_in,
            tokens_out=raw.tokens_out,
            latency_ms=raw.latency_ms,
            result_hash=raw.result_hash,
            files_touched=raw.files_touched,
            cost_weight=raw.cost_weight,
            trace_id=raw.trace_id,
            output_text=raw.output_text,
        )
        result.append(ev)

    return result


# ---------------------------------------------------------------------------
# 1.9 Action Key Helper (shared by cycle detector + waste classifier + metrics)
# ---------------------------------------------------------------------------


def _action_key(ev: TraceEvent) -> str:
    """
    Normalized action identity for cycle detection and entropy.
    Files → full path. Bash → first token. Search/Think → type only.
    No arbitrary truncation — uses semantic normalization instead.
    """
    if ev.action_type in (ActionType.FILE_READ, ActionType.FILE_WRITE, ActionType.FILE_DELETE):
        return f"{ev.action_type.value}:{ev.action_detail}"
    elif ev.action_type == ActionType.BASH:
        first_token = ev.action_detail.split()[0] if ev.action_detail.split() else "bash"
        return f"{ev.action_type.value}:{first_token}"
    elif ev.action_type == ActionType.MCP_META:
        first_token = ev.action_detail.split()[0] if ev.action_detail else "meta"
        return f"{ev.action_type.value}:{first_token}"
    return f"{ev.action_type.value}"


def _cycle_key(ev: TraceEvent) -> str:
    """Action key with result_hash — a cycle only repeats if outcomes repeat too."""
    return f"{_action_key(ev)}#{ev.result_hash}"


# ---------------------------------------------------------------------------
# 1.10 Repetition Cycle Detector (Suffix-Based)
# ---------------------------------------------------------------------------


def detect_repetition_cycles(action_sequence: list[str], min_cycle_len: int = 2, min_repeats: int = 3) -> list[dict]:
    """
    Detect repeated subsequences in an action sequence using suffix matching.
    Returns list of detected cycles with position, pattern, and repeat count.

    This catches non-revert loops: agent doing READ→BASH→READ→BASH→READ→BASH
    on the same files without any reverts. CUSUM would miss this entirely.

    Algorithm: for each candidate cycle length L (min_cycle_len..n//min_repeats),
    check if the sequence at position i repeats at i+L, i+2L, etc.
    O(n * max_cycle_len) worst case.
    """
    n = len(action_sequence)
    cycles: list[dict] = []
    seen_patterns: set[tuple] = set()

    for cycle_len in range(min_cycle_len, n // min_repeats + 1):
        for start in range(n - cycle_len * min_repeats + 1):
            pattern = tuple(action_sequence[start : start + cycle_len])
            if pattern in seen_patterns:
                continue
            # Count consecutive repeats
            repeats = 1
            pos = start + cycle_len
            while pos + cycle_len <= n:
                candidate = tuple(action_sequence[pos : pos + cycle_len])
                if candidate != pattern:
                    break
                repeats += 1
                pos += cycle_len
            if repeats >= min_repeats:
                seen_patterns.add(pattern)
                cycles.append(
                    {
                        "start": start,
                        "cycle_length": cycle_len,
                        "repeats": repeats,
                        "pattern": list(pattern),
                        "total_steps": cycle_len * repeats,
                    }
                )
    return cycles


# ---------------------------------------------------------------------------
# 1.10 Deterministic Waste Classifier
# ---------------------------------------------------------------------------


def classify_waste_deterministic(
    dag,
    thrash_window: int = 5,
    thrash_min_files: int = 4,
    thrash_min_distinct: int = 4,
    cycle_min_len: int = 2,
    cycle_min_repeats: int = 3,
) -> list[dict]:
    """
    Rule-based waste classification — no LLM needed. Categories:

    - revert_cycle: node was reverted (direct evidence of wasted work)
    - redundant_read: duplicate read of same file+hash
    - context_thrashing: >=thrash_min_files reads of >thrash_min_distinct
      distinct files in a sliding window of thrash_window steps
    - repetition_loop: detected by suffix cycle detector on action+target sequence

    All thresholds are configurable. Defaults are heuristic placeholders —
    calibrate on real traces for production use.
    """
    dag.detect_reverts()
    dag.get_effective_nodes()
    classifications: list[dict] = []
    sorted_ids = sorted(dag.events.keys())

    # 1. Revert cycles
    for nid in sorted_ids:
        ev = dag.events[nid]
        if ev.reverted_by is not None:
            classifications.append(
                {
                    "steps": [nid, nid],
                    "category": "revert_cycle",
                    "explanation": f"Step {nid} ({ev.action_type.value} {ev.action_detail[:60]}) "
                    f"was reverted by step {ev.reverted_by}",
                }
            )

    # 2. Redundant reads
    read_seen: set[tuple[str, str]] = set()
    for nid in sorted_ids:
        ev = dag.events[nid]
        if ev.action_type == ActionType.FILE_READ:
            key = (ev.action_detail, ev.result_hash)
            if key in read_seen:
                classifications.append(
                    {
                        "steps": [nid, nid],
                        "category": "redundant_read",
                        "explanation": f"Step {nid} re-read {ev.action_detail} with unchanged content",
                    }
                )
            else:
                read_seen.add(key)

    # 3. Context thrashing: sliding window
    for i in range(len(sorted_ids) - thrash_window + 1):
        window_ids = sorted_ids[i : i + thrash_window]
        files_in_window: set[str] = set()
        reads_in_window = 0
        for wid in window_ids:
            ev = dag.events[wid]
            if ev.action_type == ActionType.FILE_READ:
                reads_in_window += 1
                files_in_window.add(ev.action_detail)
        if reads_in_window >= thrash_min_files and len(files_in_window) >= thrash_min_distinct:
            classifications.append(
                {
                    "steps": [window_ids[0], window_ids[-1]],
                    "category": "context_thrashing",
                    "explanation": f"Steps {window_ids[0]}-{window_ids[-1]}: "
                    f"{len(files_in_window)} distinct files read in {thrash_window} steps",
                }
            )
            break  # report once per region

    # 4. Repetition loops via suffix detector
    action_seq = [_cycle_key(dag.events[nid]) for nid in sorted_ids]
    cycles = detect_repetition_cycles(action_seq, min_cycle_len=cycle_min_len, min_repeats=cycle_min_repeats)
    for cyc in cycles:
        start_nid = sorted_ids[cyc["start"]]
        end_idx = min(cyc["start"] + cyc["total_steps"] - 1, len(sorted_ids) - 1)
        end_nid = sorted_ids[end_idx]
        classifications.append(
            {
                "steps": [start_nid, end_nid],
                "category": "repetition_loop",
                "explanation": f"Pattern of length {cyc['cycle_length']} repeated "
                f"{cyc['repeats']} times: {cyc['pattern'][:3]}...",
            }
        )

    return classifications


# ---------------------------------------------------------------------------
# 1.11 Target-Aware Conditional Entropy
# ---------------------------------------------------------------------------


def target_aware_conditional_entropy(dag) -> float:
    """
    H(Y|X) where X and Y are (action_type, target_bucket) pairs.

    Target bucket: for FILE_READ/WRITE/DELETE, the file path.
    For BASH, the first token of the command. For SEARCH/THINK, "query"/"thought".

    This distinguishes:
    - READ a.py → BASH pytest → READ a.py → BASH pytest (productive cycle, low H)
    - READ a.py → READ b.py → READ c.py → READ d.py (exploration, high H)

    Plain action-type entropy would see both as "READ→BASH" patterns.
    """
    if len(dag.events) <= 1:
        return 0.0

    def _bucket(ev: TraceEvent) -> str:
        if ev.action_type in (ActionType.FILE_READ, ActionType.FILE_WRITE, ActionType.FILE_DELETE):
            return ev.action_detail
        elif ev.action_type == ActionType.BASH:
            return ev.action_detail.split()[0] if ev.action_detail.split() else "bash"
        elif ev.action_type == ActionType.SEARCH:
            return "search"
        elif ev.action_type == ActionType.MCP_META:
            return ev.action_detail.split()[0] if ev.action_detail else "meta"
        return "think"

    sorted_ids = [nid for nid in sorted(dag.events.keys()) if dag.events[nid].action_type != ActionType.MCP_META]
    if len(sorted_ids) <= 1:
        return 0.0
    bigram_counts: Counter = Counter()
    prefix_counts: Counter = Counter()

    for i in range(1, len(sorted_ids)):
        prev_ev = dag.events[sorted_ids[i - 1]]
        curr_ev = dag.events[sorted_ids[i]]
        prev_key = (prev_ev.action_type.value, _bucket(prev_ev))
        curr_key = (curr_ev.action_type.value, _bucket(curr_ev))
        bigram_counts[(prev_key, curr_key)] += 1
        prefix_counts[prev_key] += 1

    total = sum(bigram_counts.values())
    if total == 0:
        return 0.0

    h = 0.0
    for prev_key, prev_count in prefix_counts.items():
        p_x = prev_count / total
        for (pk, _), count in bigram_counts.items():
            if pk != prev_key:
                continue
            p_y_given_x = count / prev_count
            if p_y_given_x > 0:
                h -= p_x * p_y_given_x * math.log2(p_y_given_x)
    return h


# ---------------------------------------------------------------------------
# 2. Trace Graph Builder
# ---------------------------------------------------------------------------


class TraceDAG:
    def __init__(self):
        self.events: dict[int, TraceEvent] = {}
        self.children: dict[int, list[int]] = defaultdict(list)
        self.parents: dict[int, list[int]] = defaultdict(list)
        self.file_state: dict[str, list[int]] = defaultdict(list)
        self._reverts_detected = False
        self.bash_warnings: list[str] = []

    def add_event(self, event: TraceEvent):
        self.events[event.node_id] = event
        self.parents[event.node_id] = list(event.parent_ids)
        for pid in event.parent_ids:
            self.children[pid].append(event.node_id)
        for f in event.files_touched:
            if (event.action_type == ActionType.FILE_READ and f not in self.file_state) or event.action_type in (
                ActionType.FILE_WRITE,
                ActionType.FILE_DELETE,
            ):
                self.file_state[f].append(event.node_id)
        if event.action_type == ActionType.BASH:
            self.bash_warnings.extend(detect_bash_mutations(event.action_detail))
        self._reverts_detected = False

    def _bounded_ancestors(self, node_id: int, max_hops: int, type_filter: set[ActionType] | None = None) -> set[int]:
        visited: set[int] = set()
        frontier = [(pid, 1) for pid in self.parents.get(node_id, [])]
        while frontier:
            nid, depth = frontier.pop()
            if nid in visited or nid not in self.events or depth > max_hops:
                continue
            if type_filter is None or self.events[nid].action_type in type_filter:
                visited.add(nid)
            if depth < max_hops:
                frontier.extend((pid, depth + 1) for pid in self.parents.get(nid, []))
        return visited

    def assign_changesets(self, ancestor_hops: int = 3):
        write_nodes = {
            nid for nid, ev in self.events.items() if ev.action_type in (ActionType.FILE_WRITE, ActionType.FILE_DELETE)
        }
        if not write_nodes:
            return

        uf_parent: dict[int, int] = {n: n for n in write_nodes}

        def find(x):
            while uf_parent[x] != x:
                uf_parent[x] = uf_parent[uf_parent[x]]
                x = uf_parent[x]
            return x

        def union(a, b):
            ra, rb = find(a), find(b)
            if ra != rb:
                if ra > rb:
                    ra, rb = rb, ra
                uf_parent[rb] = ra

        parent_to_writes: dict[int, list[int]] = defaultdict(list)
        for nid in write_nodes:
            for pid in self.parents[nid]:
                parent_to_writes[pid].append(nid)
        for siblings in parent_to_writes.values():
            for i in range(1, len(siblings)):
                union(siblings[0], siblings[i])

        intent_types = {ActionType.THINK, ActionType.SEARCH}
        intent_to_writes: dict[int, list[int]] = defaultdict(list)
        for nid in write_nodes:
            for anc in self._bounded_ancestors(nid, ancestor_hops, intent_types):
                intent_to_writes[anc].append(nid)
        for group in intent_to_writes.values():
            for i in range(1, len(group)):
                union(group[0], group[i])

        for nid in write_nodes:
            self.events[nid].changeset_id = find(nid)

    def detect_reverts(self):
        if self._reverts_detected:
            return
        for ev in self.events.values():
            ev.reverted_by = None
        for _f, node_ids in self.file_state.items():
            if len(node_ids) < 2:
                continue
            hashes = [self.events[nid].result_hash for nid in node_ids]
            seen: dict[str, int] = {}
            for idx, h in enumerate(hashes):
                if h in seen:
                    for k in range(seen[h] + 1, idx):
                        self.events[node_ids[k]].reverted_by = node_ids[idx]
                seen[h] = idx
        self._reverts_detected = True

    def detect_changeset_reverts(self):
        self.detect_reverts()
        self.assign_changesets()
        cs_nodes: dict[int, list[int]] = defaultdict(list)
        for nid, ev in self.events.items():
            if ev.changeset_id is not None:
                cs_nodes[ev.changeset_id].append(nid)
        cs_status: dict[int, str] = {}
        for cs_id, nodes in cs_nodes.items():
            reverted = sum(1 for n in nodes if self.events[n].reverted_by is not None)
            if reverted == len(nodes):
                cs_status[cs_id] = "full"
            elif reverted > 0:
                cs_status[cs_id] = "partial"
            else:
                cs_status[cs_id] = "effective"
        return cs_status

    def get_effective_nodes(self, exclude_cycles: bool = True) -> set[int]:
        self.detect_reverts()
        effective = set()
        read_cache: set[tuple[str, str]] = set()

        # Identify nodes inside repetition cycles
        cycle_nodes: set[int] = set()
        if exclude_cycles:
            sorted_ids = sorted(self.events.keys())
            action_seq = [_cycle_key(self.events[nid]) for nid in sorted_ids]
            cycles = detect_repetition_cycles(action_seq)
            for cyc in cycles:
                start_idx = cyc["start"]
                end_idx = min(start_idx + cyc["total_steps"], len(sorted_ids))
                # Only strip repeated iterations (keep first occurrence of pattern)
                first_end = start_idx + cyc["cycle_length"]
                for idx in range(first_end, end_idx):
                    cycle_nodes.add(sorted_ids[idx])

        for nid in sorted(self.events.keys()):
            ev = self.events[nid]
            if ev.reverted_by is not None:
                continue
            if nid in cycle_nodes:
                continue
            if ev.action_type == ActionType.MCP_META:
                continue  # protocol overhead is never effective
            if ev.action_type == ActionType.FILE_READ:
                key = (ev.action_detail, ev.result_hash)
                if key in read_cache:
                    continue
                read_cache.add(key)
            effective.add(nid)
        return effective

    def causal_ancestors(self, node_id: int) -> set[int]:
        visited = set()
        stack = list(self.parents.get(node_id, []))
        while stack:
            nid = stack.pop()
            if nid in visited or nid not in self.events:
                continue
            visited.add(nid)
            stack.extend(self.parents.get(nid, []))
        return visited


# ---------------------------------------------------------------------------
# 3. Core Metrics
# ---------------------------------------------------------------------------


def _event_cost(ev: TraceEvent) -> float:
    """Cost weight: uses cost_weight if set, else tokens_in + tokens_out."""
    return ev.cost_weight if ev.cost_weight is not None else (ev.tokens_in + ev.tokens_out)


def path_efficiency_ratio(dag: TraceDAG) -> float:
    if not dag.events:
        return 1.0
    return len(dag.get_effective_nodes()) / len(dag.events)


def token_waste_rate(dag: TraceDAG) -> float | None:
    """Returns None when no cost data exists (all events have zero cost)."""
    effective = dag.get_effective_nodes()
    total = sum(_event_cost(e) for e in dag.events.values())
    if total == 0:
        return None
    wasted = sum(_event_cost(e) for nid, e in dag.events.items() if nid not in effective)
    return wasted / total


def conditional_entropy(dag: TraceDAG) -> float:
    if len(dag.events) <= 1:
        return 0.0
    sorted_ids = [nid for nid in sorted(dag.events.keys()) if dag.events[nid].action_type != ActionType.MCP_META]
    if len(sorted_ids) <= 1:
        return 0.0
    bigram_counts: Counter = Counter()
    prefix_counts: Counter = Counter()
    for i in range(1, len(sorted_ids)):
        prev_type = dag.events[sorted_ids[i - 1]].action_type
        curr_type = dag.events[sorted_ids[i]].action_type
        bigram_counts[(prev_type, curr_type)] += 1
        prefix_counts[prev_type] += 1
    total_bigrams = sum(bigram_counts.values())
    if total_bigrams == 0:
        return 0.0
    h = 0.0
    for prev_type, prev_count in prefix_counts.items():
        p_x = prev_count / total_bigrams
        for (px, _), count in bigram_counts.items():
            if px != prev_type:
                continue
            p_y_given_x = count / prev_count
            if p_y_given_x > 0:
                h -= p_x * p_y_given_x * math.log2(p_y_given_x)
    return h


def tool_call_entropy(dag: TraceDAG) -> float:
    counts = Counter(e.action_type for e in dag.events.values())
    total = sum(counts.values())
    if total == 0:
        return 0.0
    h = 0.0
    for c in counts.values():
        p = c / total
        if p > 0:
            h -= p * math.log2(p)
    return h


def backtrack_depth(dag: TraceDAG) -> int:
    dag.detect_reverts()
    return sum(1 for e in dag.events.values() if e.reverted_by is not None)


def first_pass_success_rate(dag: TraceDAG) -> float | None:
    """Returns None for read-only sessions (no writes to evaluate)."""
    dag.detect_reverts()
    writes = [e for e in dag.events.values() if e.action_type in (ActionType.FILE_WRITE, ActionType.FILE_DELETE)]
    if not writes:
        return None
    return sum(1 for e in writes if e.reverted_by is None) / len(writes)


# ---------------------------------------------------------------------------
# 3.5 Quality Metrics (Output Correctness)
# ---------------------------------------------------------------------------


def build_error_count(dag: TraceDAG) -> int:
    count = 0
    for ev in dag.events.values():
        if ev.action_type == ActionType.BASH and ev.output_text and _SHELL_ERROR_RE.search(ev.output_text):
            count += 1
    return count


def unresolved_error_count(dag: TraceDAG, resolution_window: int = 5) -> int:
    sorted_ids = sorted(dag.events.keys())
    count = 0
    for i, nid in enumerate(sorted_ids):
        ev = dag.events[nid]
        if ev.action_type != ActionType.BASH or not ev.output_text:
            continue
        if not _SHELL_ERROR_RE.search(ev.output_text):
            continue
        resolved = False
        for j in range(i + 1, min(i + 1 + resolution_window, len(sorted_ids))):
            future_ev = dag.events[sorted_ids[j]]
            if future_ev.action_type == ActionType.FILE_WRITE:
                resolved = True
                break
        if not resolved:
            count += 1
    return count


def write_without_verify_ratio(dag: TraceDAG) -> float:
    """Fraction of write batches not followed by a verify command.

    A "batch" is a run of writes separated only by reads, searches, or thinks
    (normal interleaving during development). A BASH event breaks the batch.
    A batch is "verified" if any BASH event between the batch end and the next
    batch matches a build/test/run command.
    """
    sorted_ids = sorted(dag.events.keys())
    if not sorted_ids:
        return 0.0

    batch_break_types = {ActionType.BASH}
    batches: list[tuple[int, int]] = []
    batch_start = None
    batch_end = None
    for i, nid in enumerate(sorted_ids):
        ev = dag.events[nid]
        if ev.action_type == ActionType.FILE_WRITE:
            if batch_start is None:
                batch_start = i
            batch_end = i
        elif ev.action_type in batch_break_types:
            if batch_start is not None:
                batches.append((batch_start, batch_end))
                batch_start = None
                batch_end = None
    if batch_start is not None:
        batches.append((batch_start, batch_end))

    if not batches:
        return 0.0

    unverified = 0
    for _, last_write_idx in batches:
        verified = False
        for j in range(last_write_idx + 1, len(sorted_ids)):
            future_ev = dag.events[sorted_ids[j]]
            if future_ev.action_type == ActionType.FILE_WRITE:
                break
            if future_ev.action_type == ActionType.BASH and _VERIFY_COMMAND_RE.search(future_ev.action_detail):
                verified = True
                break
        if not verified:
            unverified += 1

    return unverified / len(batches)


def file_churn_rate(dag: TraceDAG) -> float:
    file_hashes: dict[str, list[str]] = defaultdict(list)
    for nid in sorted(dag.events.keys()):
        ev = dag.events[nid]
        if ev.action_type == ActionType.FILE_WRITE:
            for f in ev.files_touched:
                file_hashes[f].append(ev.result_hash)
    if not file_hashes:
        return 0.0
    churned = sum(1 for hashes in file_hashes.values() if len(set(hashes)) >= 2)
    return churned / len(file_hashes)


def orphan_dependency_count(dag: TraceDAG) -> int:
    installed_packages: set[str] = set()
    for ev in dag.events.values():
        if ev.action_type != ActionType.BASH:
            continue
        match = _PACKAGE_INSTALL_RE.search(ev.action_detail)
        if not match:
            continue
        for token in match.group(1).split():
            if token.startswith("-"):
                continue
            pkg_name = re.split(r"[@=<>~!]", token)[0].strip()
            if pkg_name:
                installed_packages.add(pkg_name)
    if not installed_packages:
        return 0
    all_write_content = []
    for ev in dag.events.values():
        if ev.action_type == ActionType.FILE_WRITE and ev.output_text:
            all_write_content.append(ev.output_text)
        if ev.action_type == ActionType.FILE_WRITE and ev.action_detail:
            all_write_content.append(ev.action_detail)
    write_blob = "\n".join(all_write_content)
    return sum(1 for pkg in installed_packages if pkg not in write_blob)


def final_session_success(dag: TraceDAG) -> float:
    for nid in sorted(dag.events.keys(), reverse=True):
        ev = dag.events[nid]
        if ev.action_type == ActionType.BASH:
            if ev.output_text and _SHELL_ERROR_RE.search(ev.output_text):
                return 0.0
            return 1.0
    return 1.0


# ---------------------------------------------------------------------------
# 4. EWMA-Adaptive Windowed CUSUM Stuck Detector
# ---------------------------------------------------------------------------


class CUSUMStuckDetector:
    """
    EWMA-adaptive windowed CUSUM. Baseline μ₀ drifts via exponential moving
    average so the detector tracks non-stationary revert rates.

    Pipeline: raw binary → sliding window average → CUSUM vs EWMA baseline.

    ewma_alpha=0 → fixed baseline (legacy). ewma_alpha>0 → drifting baseline.
    """

    def __init__(
        self,
        baseline_revert_rate: float = 0.15,
        h: float = 4.0,
        k: float = 0.5,
        warmup: int = 0,
        window: int = 1,
        ewma_alpha: float = 0.0,
    ):
        self.h = h
        self.k = k
        self.warmup = warmup
        self.window = max(1, window)
        self.ewma_alpha = ewma_alpha
        self.mu0 = baseline_revert_rate
        self.S_pos = 0.0
        self.S_neg = 0.0
        self.n = 0
        self.alarm = False
        self.alarm_step: int | None = None
        self._warmup_sum = 0.0
        self._warmup_done = warmup == 0
        self._ring: list[float] = []

    def update(self, is_revert: bool) -> bool:
        x = 1.0 if is_revert else 0.0
        self.n += 1

        self._ring.append(x)
        if len(self._ring) > self.window:
            self._ring.pop(0)

        if not self._warmup_done:
            self._warmup_sum += x
            if self.n >= self.warmup:
                self.mu0 = max(0.01, min(self._warmup_sum / self.n, 0.99))
                self._warmup_done = True
            return False

        smoothed = sum(self._ring) / len(self._ring)

        # EWMA baseline drift — use previous μ₀ for CUSUM, then update
        mu0_prev = self.mu0
        if self.ewma_alpha > 0:
            self.mu0 = self.ewma_alpha * smoothed + (1 - self.ewma_alpha) * self.mu0
            self.mu0 = max(0.01, min(self.mu0, 0.99))

        self.S_pos = max(0.0, self.S_pos + (smoothed - mu0_prev) - self.k)
        self.S_neg = max(0.0, self.S_neg - (smoothed - mu0_prev) - self.k)
        if self.S_pos > self.h or self.S_neg > self.h:
            if not self.alarm:
                self.alarm = True
                self.alarm_step = self.n
            return True
        return False

    def reset(self):
        self.S_pos = 0.0
        self.S_neg = 0.0
        self.alarm = False
        self.alarm_step = None
        self._warmup_sum = 0.0
        self._warmup_done = self.warmup == 0
        self.n = 0
        self._ring = []


# ---------------------------------------------------------------------------
# 5. LLM-as-Judge Prompt Generator + Deterministic Validator
# ---------------------------------------------------------------------------

_JUDGE_THRESHOLDS = {
    TaskComplexity.TARGETED_FIX: {"per_floor_for_ab": 0.5, "twr_ceil_for_waste": 0.4},
    TaskComplexity.EXPLORATION: {"per_floor_for_ab": 0.15, "twr_ceil_for_waste": 0.7},
    TaskComplexity.GREENFIELD: {"per_floor_for_ab": 0.35, "twr_ceil_for_waste": 0.5},
}


def validate_judge_output(judge_json: dict, metrics: dict, complexity: TaskComplexity) -> dict:
    """
    Deterministic post-processing: enforce threshold constraints on LLM judge
    output. Corrects violations. Returns corrected dict with 'corrections' list.
    """
    result = dict(judge_json)
    corrections: list[str] = []
    thresholds = _JUDGE_THRESHOLDS[complexity]

    # Rule 1: PER < floor → grade cannot be A or B
    per = metrics.get("path_efficiency_ratio", 1.0)
    grade = result.get("efficiency_grade", "C")
    if per < thresholds["per_floor_for_ab"] and grade in ("A", "B"):
        result["efficiency_grade"] = "C"
        corrections.append(f"Downgraded {grade}->C: PER={per:.2f} < {thresholds['per_floor_for_ab']}")

    # Rule 2: TWR > ceiling → warn if waste classifications insufficient
    twr = metrics.get("token_waste_rate") or 0.0
    if twr > thresholds["twr_ceil_for_waste"]:
        non_effective = metrics.get("total_events", 0) - metrics.get("effective_events", 0)
        classified = set()
        for wc in result.get("waste_classifications", []):
            steps = wc.get("steps", [])
            if len(steps) == 2:
                classified.update(range(steps[0], steps[1] + 1))
        if non_effective > 0 and len(classified) < non_effective * 0.5:
            corrections.append(
                f"Insufficient waste coverage: {len(classified)}/{non_effective} "
                f"classified, TWR={twr:.2f} > {thresholds['twr_ceil_for_waste']}"
            )

    # Rule 3: Scores clamped to [1, 5]
    for fld in ("correctness_score", "completeness_score", "minimality_score"):
        val = result.get(fld)
        if isinstance(val, (int, float)) and not (1 <= val <= 5):
            result[fld] = max(1, min(5, round(val)))
            corrections.append(f"Clamped {fld} to [1,5]")

    result["corrections"] = corrections
    return result


def compute_all_metrics(dag: TraceDAG) -> dict:
    fpsr = first_pass_success_rate(dag)
    twr = token_waste_rate(dag)
    sorted_ids = sorted(dag.events.keys())
    action_seq = [_cycle_key(dag.events[nid]) for nid in sorted_ids]
    cycles = detect_repetition_cycles(action_seq)

    # Count distinct (action_type, target_bucket) pairs for entropy normalization
    distinct_targets: set[tuple[str, str]] = set()
    for nid in sorted_ids:
        ev = dag.events[nid]
        if ev.action_type == ActionType.MCP_META:
            continue
        if ev.action_type in (ActionType.FILE_READ, ActionType.FILE_WRITE, ActionType.FILE_DELETE):
            bucket = ev.action_detail
        elif ev.action_type == ActionType.BASH:
            bucket = ev.action_detail.split()[0] if ev.action_detail.split() else "bash"
        elif ev.action_type == ActionType.SEARCH:
            bucket = "search"
        else:
            bucket = "think"
        distinct_targets.add((ev.action_type.value, bucket))

    return {
        "path_efficiency_ratio": round(path_efficiency_ratio(dag), 4),
        "token_waste_rate": round(twr, 4) if twr is not None else None,
        "conditional_entropy_bits": round(conditional_entropy(dag), 4),
        "target_aware_entropy_bits": round(target_aware_conditional_entropy(dag), 4),
        "marginal_entropy_bits": round(tool_call_entropy(dag), 4),
        "backtrack_depth": backtrack_depth(dag),
        "first_pass_success_rate": round(fpsr, 4) if fpsr is not None else None,
        "total_events": len(dag.events),
        "effective_events": len(dag.get_effective_nodes()),
        "repetition_cycles": len(cycles),
        "distinct_target_count": len(distinct_targets),
        "build_error_count": build_error_count(dag),
        "unresolved_error_count": unresolved_error_count(dag),
        "write_without_verify_ratio": round(write_without_verify_ratio(dag), 4),
        "file_churn_rate": round(file_churn_rate(dag), 4),
        "orphan_dependency_count": orphan_dependency_count(dag),
        "final_session_success": final_session_success(dag),
    }


def compute_per_trace_metrics(dag: TraceDAG) -> dict[str, dict]:
    """Break down key metrics by trace_id within a session-level DAG.

    Returns {trace_id: {total_events, effective_events, per, twr, fpsr}} for
    each trace_id present. Effective/reverted status is determined at the
    session level (cross-trace reverts are captured), then attributed back
    to originating traces.
    """
    trace_ids = {ev.trace_id for ev in dag.events.values() if ev.trace_id}
    if not trace_ids:
        return {}

    effective = dag.get_effective_nodes()
    per_trace: dict[str, dict] = {}

    for tid in sorted(trace_ids):
        nodes = {nid for nid, ev in dag.events.items() if ev.trace_id == tid}
        eff_nodes = nodes & effective
        total = len(nodes)
        eff = len(eff_nodes)

        total_cost = sum(_event_cost(dag.events[nid]) for nid in nodes)
        wasted_cost = sum(_event_cost(dag.events[nid]) for nid in nodes if nid not in effective)
        twr = (wasted_cost / total_cost) if total_cost > 0 else None

        writes = [
            nid for nid in nodes if dag.events[nid].action_type in (ActionType.FILE_WRITE, ActionType.FILE_DELETE)
        ]
        if writes:
            non_reverted = sum(1 for nid in writes if dag.events[nid].reverted_by is None)
            fpsr = non_reverted / len(writes)
        else:
            fpsr = None

        per_trace[tid] = {
            "total_events": total,
            "effective_events": eff,
            "path_efficiency_ratio": round(eff / total, 4) if total > 0 else 1.0,
            "token_waste_rate": round(twr, 4) if twr is not None else None,
            "first_pass_success_rate": round(fpsr, 4) if fpsr is not None else None,
        }

    return per_trace


def summarize_trace(dag: TraceDAG, max_events: int = 50) -> list[dict]:
    summary = []
    effective = dag.get_effective_nodes()
    for nid in sorted(dag.events.keys())[:max_events]:
        ev = dag.events[nid]
        summary.append(
            {
                "step": nid,
                "action": ev.action_type.value,
                "detail": ev.action_detail[:120],
                "tokens": ev.tokens_in + ev.tokens_out,
                "latency_ms": ev.latency_ms,
                "effective": nid in effective,
                "reverted": ev.reverted_by is not None,
                "parent_ids": ev.parent_ids,
                "changeset_id": ev.changeset_id,
            }
        )
    return summary


def generate_judge_prompt(
    task_description: str, dag: TraceDAG, complexity: TaskComplexity = TaskComplexity.TARGETED_FIX
) -> str:
    metrics = compute_all_metrics(dag)
    trace_summary = summarize_trace(dag)
    cs_status = dag.detect_changeset_reverts()
    thresholds = _JUDGE_THRESHOLDS[complexity]

    prompt = f"""You are an expert evaluator of AI coding agent behavior.

## Task the agent was given
{task_description}

## Task Complexity Class
{complexity.value} — thresholds are calibrated for this class.

## Deterministic Metrics (pre-computed, ground truth)
{json.dumps(metrics, indent=2)}

## Changeset Status
{json.dumps({str(k): v for k, v in cs_status.items()}, indent=2)}

## Agent Action Trace (step-by-step, with causal parent_ids)
{json.dumps(trace_summary, indent=2)}

## Your Evaluation

Produce a JSON object with exactly these fields:

{{
  "strategic_phases": [
    {{"steps": [start, end], "label": "description of what agent was doing"}}
  ],
  "waste_classifications": [
    {{"steps": [start, end], "category": "redundant_exploration|wrong_approach|context_thrashing|hallucination_recovery|other", "explanation": "..."}}
  ],
  "correctness_score": 1-5,
  "completeness_score": 1-5,
  "minimality_score": 1-5,
  "efficiency_grade": "A|B|C|D|F",
  "one_line_summary": "..."
}}

Rules (calibrated for task complexity = {complexity.value}):
- If path_efficiency_ratio < {thresholds["per_floor_for_ab"]}, efficiency_grade cannot be A or B.
- If token_waste_rate > {thresholds["twr_ceil_for_waste"]}, at least 50% of non-effective steps should appear in waste_classifications.
- Classify ALL steps marked "effective": false in the trace.
- Changesets marked "partial" indicate cross-file inconsistency — flag these.
- Be specific in explanations. Reference step numbers and causal parent_ids.

NOTE: Your output will be validated and corrected by a deterministic post-processor.
Threshold violations will be automatically fixed. Focus on accurate classification.

Respond with ONLY the JSON object, no other text."""

    return prompt


# ---------------------------------------------------------------------------
# 6. Span-Level Detection Functions (v4.4)
# ---------------------------------------------------------------------------


def _aggregate_span_stats(span_metadata: list[dict], config: dict) -> dict:
    """Count errors, timeouts, latency coverage, total tool calls from span metadata."""
    timeout_threshold = config.get("timeout_threshold_ms", DEFAULT_CONFIG["timeout_threshold_ms"])

    stats = {
        "tool_error_count": 0,
        "tool_timeout_count": 0,
        "total_tool_calls": 0,
        "latency_data_available_count": 0,
    }

    for span in span_metadata:
        if span.get("type") != "tool_call":
            continue

        stats["total_tool_calls"] += 1

        error_msg = span.get("error", "")
        status = span.get("status", "")
        if error_msg or status == "error":
            stats["tool_error_count"] += 1

        latency = span.get("latency_ms")
        if latency is not None and latency != 0:
            stats["latency_data_available_count"] += 1
        if latency and latency > timeout_threshold:
            stats["tool_timeout_count"] += 1

    if stats["total_tool_calls"] > 0:
        stats["latency_coverage"] = round(stats["latency_data_available_count"] / stats["total_tool_calls"], 4)
    else:
        stats["latency_coverage"] = None

    return stats


def _normalize_paths_in_input(tool_input):
    """Normalize file paths in tool input for dedup key computation."""
    if isinstance(tool_input, str):
        if tool_input.startswith(("/", "./")) or ".." in tool_input:
            return os.path.normpath(tool_input)
        return tool_input
    elif isinstance(tool_input, dict):
        return {k: _normalize_paths_in_input(v) for k, v in tool_input.items()}
    elif isinstance(tool_input, list):
        return [_normalize_paths_in_input(item) for item in tool_input]
    return tool_input


def _compute_dedup_key(tool_name: str, tool_input) -> str:
    """Compute dedup key for a tool call: name + MD5 of normalized input."""
    tool_input = _normalize_paths_in_input(tool_input)

    if isinstance(tool_input, dict):
        normalized = json.dumps(tool_input, sort_keys=True)
    elif isinstance(tool_input, str):
        try:
            parsed = json.loads(tool_input)
            if isinstance(parsed, (dict, list)):
                parsed = _normalize_paths_in_input(parsed)
                normalized = json.dumps(parsed, sort_keys=True)
            else:
                normalized = tool_input
        except (json.JSONDecodeError, TypeError):
            normalized = tool_input
    else:
        normalized = str(tool_input) if tool_input is not None else ""

    input_hash = hashlib.md5(normalized.encode(), usedforsecurity=False).hexdigest()
    return f"{tool_name}:{input_hash}"


def _detect_duplicates(spans: list[dict]) -> tuple[list[dict], int]:
    """Detect duplicate tool calls via dedup key."""
    findings = []
    seen_keys: dict[str, int] = {}
    dup_count = 0

    tool_call_spans = [(i, s) for i, s in enumerate(spans) if s.get("type") == "tool_call"]

    for i, span in tool_call_spans:
        tool_name = span.get("name", "")
        dedup_key = _compute_dedup_key(tool_name, span.get("input"))

        if dedup_key in seen_keys:
            findings.append(
                {
                    "category": "duplicate_tool_call",
                    "severity": "low",
                    "axis": "efficiency",
                    "evidence": f"Tool {tool_name} called with identical input at span {i} (first at {seen_keys[dedup_key]})",
                    "span_index": i,
                }
            )
            dup_count += 1
        else:
            seen_keys[dedup_key] = i

    return findings, dup_count


def _detect_retry_patterns(
    spans: list[dict],
    config: dict | None = None,
) -> tuple[list[dict], dict]:
    """Detect ignored failures, successful retries, and late recoveries.

    Uses proximity-bounded exact match, then lookahead window for adapted
    retries, then falls back to ignored_failure. Every failed tool_call
    gets exactly one classification.
    """
    config = config or {}
    lookahead = config.get("retry_lookahead_window", DEFAULT_CONFIG["retry_lookahead_window"])
    max_distance = config.get("max_retry_distance", DEFAULT_CONFIG["max_retry_distance"])

    findings: list[dict] = []
    stats = {
        "ignored_failure_count": 0,
        "retry_success_count": 0,
        "late_recovery_count": 0,
    }

    def _is_failed(span):
        return bool(span.get("error", "")) or span.get("status") == "error"

    tc_spans = [(i, s) for i, s in enumerate(spans) if s.get("type") == "tool_call"]
    tc_position = {gi: pos for pos, (gi, _) in enumerate(tc_spans)}

    success_index: dict[str, list[tuple[int, dict]]] = {}
    for gi, span in tc_spans:
        if not _is_failed(span):
            key = _compute_dedup_key(span.get("name", ""), span.get("input"))
            success_index.setdefault(key, []).append((gi, span))

    for gi, span in tc_spans:
        if not _is_failed(span):
            continue

        tool_name = span.get("name", "")
        dedup_key = _compute_dedup_key(tool_name, span.get("input"))

        # Step 1: Proximity-bounded exact match
        matched = False
        if dedup_key in success_index:
            for succ_gi, _succ_span in success_index[dedup_key]:
                if succ_gi <= gi:
                    continue
                distance = tc_position[succ_gi] - tc_position[gi] - 1
                if distance <= max_distance:
                    findings.append(
                        {
                            "category": "retry_success",
                            "severity": "low",
                            "axis": "reliability",
                            "evidence": f"Tool {tool_name} failed at span {gi}, succeeded at {succ_gi}",
                            "span_index": gi,
                        }
                    )
                    stats["retry_success_count"] += 1
                else:
                    findings.append(
                        {
                            "category": "late_recovery",
                            "severity": "low",
                            "axis": "reliability",
                            "evidence": f"Tool {tool_name} failed at span {gi}, recovered at {succ_gi} ({distance} tool calls apart)",
                            "span_index": gi,
                        }
                    )
                    stats["late_recovery_count"] += 1
                matched = True
                break

        if matched:
            continue

        # Step 2: Lookahead window — adapted retry (same tool name, different input)
        window_end = min(gi + 1 + lookahead, len(spans))
        has_adapted_retry = False
        for j in range(gi + 1, window_end):
            candidate = spans[j]
            if candidate.get("type") != "tool_call":
                continue
            if candidate.get("name") == tool_name and not _is_failed(candidate):
                has_adapted_retry = True
                break

        if has_adapted_retry:
            findings.append(
                {
                    "category": "retry_success",
                    "severity": "low",
                    "axis": "reliability",
                    "evidence": f"Tool {tool_name} failed at span {gi}, adapted retry within {lookahead} spans",
                    "span_index": gi,
                }
            )
            stats["retry_success_count"] += 1
            continue

        # Step 3: Ignored failure
        findings.append(
            {
                "category": "ignored_failure",
                "severity": "high",
                "axis": "reliability",
                "evidence": f"Tool {tool_name} failed at span {gi}, no retry found",
                "span_index": gi,
            }
        )
        stats["ignored_failure_count"] += 1

    return findings, stats


def _scan_adversarial_content(
    span_metadata: list[dict],
    config: dict,
) -> tuple[list[dict], dict, list[str]]:
    """Scan all string fields for adversarial patterns."""
    max_length = config.get("max_field_scan_length", DEFAULT_CONFIG["max_field_scan_length"])
    secret_patterns = config.get("secret_patterns", DEFAULT_CONFIG["secret_patterns"])
    if not isinstance(secret_patterns, list):
        secret_patterns = DEFAULT_CONFIG["secret_patterns"]

    findings: list[dict] = []
    warnings: list[str] = []
    found_patterns: set[str] = set()
    was_truncated = False
    depth_limit_exceeded = False
    truncation_in_tool_call = False
    instance_counts: Counter = Counter()

    def extract_strings(obj, depth=0, is_tool_call=False):
        nonlocal was_truncated, depth_limit_exceeded, truncation_in_tool_call

        if depth > 10:
            depth_limit_exceeded = True
            return []

        strings = []
        if isinstance(obj, str):
            if len(obj) > max_length:
                was_truncated = True
                if is_tool_call:
                    truncation_in_tool_call = True
                strings.append(obj[:max_length])
            else:
                strings.append(obj)
        elif isinstance(obj, dict):
            for v in obj.values():
                strings.extend(extract_strings(v, depth + 1, is_tool_call))
        elif isinstance(obj, list):
            for item in obj:
                strings.extend(extract_strings(item, depth + 1, is_tool_call))
        return strings

    # Req 5: Structured evaluation output in JSON fields — exact match, info/observation
    for span in span_metadata:
        for data in [span.get("input"), span.get("output")]:
            if isinstance(data, str):
                try:
                    data = json.loads(data)
                except (json.JSONDecodeError, TypeError):
                    pass
            if isinstance(data, dict):
                for key in data:
                    if key.lower() in _EVAL_JSON_KEYS:
                        instance_counts["score_assertion"] += 1
                        if "score_assertion_json" not in found_patterns:
                            findings.append(
                                {
                                    "category": "score_assertion",
                                    "severity": "info",
                                    "axis": "observation",
                                    "evidence": f"Structured evaluation field detected: {key}={data[key]}"[:300],
                                    "span_index": None,
                                }
                            )
                            found_patterns.add("score_assertion_json")

    # Extract all strings for pattern matching
    all_strings: list[str] = []
    for span in span_metadata:
        is_tc = span.get("type") == "tool_call"
        all_strings.extend(extract_strings(span, is_tool_call=is_tc))

    for text in all_strings:
        # Req 6: html_comment_injection → info/observation
        if _HTML_COMMENT_EVAL_RE.search(text):
            instance_counts["html_comment_injection"] += 1
            if "html_comment_injection" not in found_patterns:
                findings.append(
                    {
                        "category": "html_comment_injection",
                        "severity": "info",
                        "axis": "observation",
                        "evidence": f"HTML comment with eval keyword detected: {text[:100]}...",
                        "span_index": None,
                    }
                )
                found_patterns.add("html_comment_injection")

        # Req 7: system_prompt_mimicry → info/observation
        if _SYSTEM_PROMPT_RE.search(text):
            instance_counts["system_prompt_mimicry"] += 1
            if "system_prompt_mimicry" not in found_patterns:
                findings.append(
                    {
                        "category": "system_prompt_mimicry",
                        "severity": "info",
                        "axis": "observation",
                        "evidence": f"System prompt pattern detected: {text[:100]}...",
                        "span_index": None,
                    }
                )
                found_patterns.add("system_prompt_mimicry")

        # Req 10: score_assertion_text branch REMOVED

        # Req 9: zero_width_unicode → high/data_integrity
        if _ZERO_WIDTH_RE.search(text):
            instance_counts["zero_width_unicode"] += 1
            if "zero_width_unicode" not in found_patterns:
                findings.append(
                    {
                        "category": "zero_width_unicode",
                        "severity": "high",
                        "axis": "data_integrity",
                        "evidence": "6+ consecutive zero-width characters detected",
                        "span_index": None,
                    }
                )
                found_patterns.add("zero_width_unicode")

    # Req 8: Secret access detection (replaces evaluator_path_probing)
    for span in span_metadata:
        if span.get("type") == "tool_call":
            input_str = str(span.get("input", ""))
            for pattern in secret_patterns:
                if pattern in input_str:
                    instance_counts["secret_access"] += 1
                    if "secret_access" not in found_patterns:
                        findings.append(
                            {
                                "category": "secret_access",
                                "severity": "high",
                                "axis": "security",
                                "evidence": f"Secret access pattern matched: {pattern}",
                                "span_index": None,
                            }
                        )
                        found_patterns.add("secret_access")

    # Req 12: Truncation handling with scan completeness
    if was_truncated or depth_limit_exceeded:
        severity = "medium" if truncation_in_tool_call else "low"
        reasons = []
        if was_truncated:
            reasons.append(f"fields exceeded {max_length} chars")
        if depth_limit_exceeded:
            reasons.append("nesting depth exceeded 10 levels")
        evidence = f"Scan incomplete: {' and '.join(reasons)}."
        findings.append(
            {
                "category": "field_truncated",
                "severity": severity,
                "axis": "security",
                "evidence": evidence,
                "span_index": None,
            }
        )
        warnings.append(evidence)

    # Req 11: Stats with pre-dedup counts
    non_trunc = [f for f in findings if f["category"] != "field_truncated"]
    stats = {
        "injection_finding_count": len(non_trunc),
        "has_adversarial_content": 1 if found_patterns else 0,
        "unique_pattern_types_found": len(found_patterns),
        "total_injection_instances": sum(instance_counts.values()),
        "pattern_type_counts": dict(instance_counts),
        "scan_completeness": "partial" if (was_truncated or depth_limit_exceeded) else "full",
    }

    return findings, stats, warnings


# ---------------------------------------------------------------------------
# 7. Full Pipeline
# ---------------------------------------------------------------------------


def analyze_session(
    task: str,
    events: list[TraceEvent],
    complexity: TaskComplexity = TaskComplexity.TARGETED_FIX,
    cusum_warmup: int = 0,
    cusum_window: int = 1,
    cusum_ewma_alpha: float = 0.0,
    include_judge: bool = False,
    span_metadata: list[dict] | None = None,
    config: dict | None = None,
) -> dict:
    config = config or {}

    dag = TraceDAG()
    for ev in events:
        dag.add_event(ev)

    dag.detect_reverts()
    dag.assign_changesets()
    cs_status = dag.detect_changeset_reverts()

    cusum = CUSUMStuckDetector(warmup=cusum_warmup, window=cusum_window, ewma_alpha=cusum_ewma_alpha)
    stuck_alerts = []
    for nid in sorted(dag.events.keys()):
        ev = dag.events[nid]
        if cusum.update(ev.reverted_by is not None) and cusum.alarm_step == cusum.n:
            stuck_alerts.append(nid)

    metrics = compute_all_metrics(dag)
    waste_classifications = classify_waste_deterministic(dag)

    # Span-level detection when span_metadata provided
    findings: list[dict] = []
    warnings: list[str] = []
    malformed_count = 0

    if span_metadata:
        try:
            span_stats = _aggregate_span_stats(span_metadata, config)
            metrics.update(span_stats)
        except Exception:
            warnings.append("Span stats aggregation failed")
            malformed_count += 1

        try:
            dup_findings, dup_count = _detect_duplicates(span_metadata)
            findings.extend(dup_findings)
            metrics["duplicate_tool_call_count"] = dup_count
        except Exception:
            warnings.append("Duplicate detection failed")
            malformed_count += 1

        try:
            retry_findings, retry_stats = _detect_retry_patterns(span_metadata, config)
            findings.extend(retry_findings)
            metrics.update(retry_stats)
        except Exception:
            warnings.append("Retry pattern detection failed")
            malformed_count += 1

        try:
            adv_findings, adv_stats, adv_warnings = _scan_adversarial_content(span_metadata, config)
            findings.extend(adv_findings)
            metrics.update(adv_stats)
            warnings.extend(adv_warnings)
        except Exception:
            warnings.append("Adversarial scan failed")
            malformed_count += 1

        # MCP-specific analysis
        from poc_mcp_analysis import run_mcp_analysis

        metrics["mcp_analysis"] = run_mcp_analysis(span_metadata, metrics["token_waste_rate"] or 0.0)

    per_trace = compute_per_trace_metrics(dag)

    result = {
        "metrics": metrics,
        "stuck_alerts": stuck_alerts,
        "effective_node_ids": sorted(dag.get_effective_nodes()),
        "changeset_status": cs_status,
        "bash_warnings": dag.bash_warnings,
        "waste_classifications": waste_classifications,
        "dag_children": dict(dag.children),
        "findings": findings,
        "data_quality": {
            "has_span_metadata": span_metadata is not None,
            "span_count": len(span_metadata) if span_metadata else 0,
            "malformed_span_count": malformed_count,
            "truncated_fields": any(f.get("category") == "field_truncated" for f in findings),
            "warnings": warnings,
            "scan_completeness": metrics.get("scan_completeness", "full") if span_metadata else None,
        },
    }

    if per_trace:
        result["per_trace_metrics"] = per_trace

    if include_judge:
        result["judge_prompt"] = generate_judge_prompt(task, dag, complexity)

    return result
