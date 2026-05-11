# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-FileCopyrightText: 2026 Swathi Saravanan <ss4522@cornell.edu>
# SPDX-License-Identifier: AGPL-3.0-only

"""Structural scorer: rule-based scoring for Tool Efficiency and Tool Failures.

Parses spans from ClickHouse to detect penalties without needing an LLM.
Includes MatchingEngine and NumericComparator for hardened string matching
(BenchJack Pattern 5 mitigation).
"""

import hashlib
import json
import logging
import re

from models.scoring import ScoringDimension

logger = logging.getLogger(__name__)

# Timeout threshold in ms for tool calls (default when no per-tool override set)
DEFAULT_TIMEOUT_MS = 30_000

# Max spans between two matching tool calls before we stop calling them duplicates
DUPLICATE_SPAN_WINDOW = 10

# Max spans between error and retry before we stop considering the retry related
RETRY_SPAN_WINDOW = 10

# Tool names that imply a state change — reads before and after such a tool are
# not flagged as duplicates because the underlying data may have changed.
_STATE_CHANGE_PATTERN = re.compile(
    r"\b(?:write|edit|create|update|delete|patch|modify|save|append|remove|rename|move|exec|run|install|commit|push)\b",
    re.IGNORECASE,
)

# Boilerplate tokens that should NOT be treated as distinctive content when
# checking whether a tool result is referenced later.
_BOILERPLATE_TOKENS = frozenset(
    {
        # license / copyright headers
        "copyright",
        "license",
        "licensed",
        "apache",
        "permission",
        "warranty",
        "notwithstanding",
        "liability",
        # POSIX `ls -l` prefixes
        "total",
        "drwx",
        "drwxr",
        "rwxr",
        "rwxrwxr",
        # common shell / filesystem noise
        "usr",
        "bin",
        "home",
        "root",
        "null",
        "true",
        "false",
        "none",
    }
)

_RE_DISTINCTIVE_TOKEN = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_\-.]{3,}")


class StructuralScorer:
    """Rule-based scorer for tool_efficiency and tool_failures dimensions."""

    def __init__(
        self,
        timeout_ms: int = DEFAULT_TIMEOUT_MS,
        tool_timeouts: dict[str, int] | None = None,
    ):
        self.timeout_ms = timeout_ms
        self.tool_timeouts = {k.lower(): v for k, v in (tool_timeouts or {}).items()}

    def _timeout_for(self, tool_name: str) -> int:
        """Resolve the effective timeout for a given tool name."""
        if not tool_name:
            return self.timeout_ms
        return self.tool_timeouts.get(tool_name.lower(), self.timeout_ms)

    def score_tool_efficiency(
        self,
        spans: list[dict],
        agent_id: str,
    ) -> list[dict]:
        """Detect tool efficiency penalties from spans.

        Returns list of dicts with keys: event_name, evidence, trace_event_index.
        """
        penalties: list[dict] = []
        tool_call_spans = [s for s in spans if s.get("type") == "tool_call"]
        non_tool_spans = [s for s in spans if s.get("type") != "tool_call"]

        # Ungrounded claims: for each assertion span, check whether ANY tool
        # call output is referenced. We don't gate on total tool-call count —
        # one unrelated tool call shouldn't excuse a fabricated assertion.
        assertion_spans = [s for s in non_tool_spans if _span_asserts_external_state(s)]
        if assertion_spans:
            tool_outputs = [str(s.get("output") or "") for s in tool_call_spans if s.get("output")]
            unsupported = [s for s in assertion_spans if not _assertion_is_grounded(s, tool_outputs)]
            if unsupported:
                penalties.append(
                    {
                        "event_name": "ungrounded_claims",
                        "dimension": ScoringDimension.tool_efficiency,
                        "evidence": (
                            f"Agent {agent_id} made {len(unsupported)} assertion(s) about external state "
                            f"with no supporting tool output (of {len(tool_call_spans)} tool call(s) in trace)."
                        ),
                        "trace_event_index": None,
                    }
                )

        # Duplicate tool calls: same tool name + same input hash, within a
        # short window, with no state-changing tool call in between.
        for idx, span in enumerate(tool_call_spans):
            key = _span_dedup_key(span)
            # Walk back up to DUPLICATE_SPAN_WINDOW spans looking for an exact match.
            window_start = max(0, idx - DUPLICATE_SPAN_WINDOW)
            earlier = tool_call_spans[window_start:idx]
            for prior_offset, prior in enumerate(earlier):
                if _span_dedup_key(prior) != key:
                    continue
                between = earlier[prior_offset + 1 :]
                if _has_state_change(between):
                    continue  # read-write-read is not a duplicate
                penalties.append(
                    {
                        "event_name": "duplicate_tool_call",
                        "dimension": ScoringDimension.tool_efficiency,
                        "evidence": (
                            f"Duplicate call to '{span.get('name', '')}' with same params. "
                            f"First at index {window_start + prior_offset}, duplicate at index {idx}."
                        ),
                        "trace_event_index": idx,
                    }
                )
                break

        # Unused tool results: tool output not referenced by any subsequent span.
        # We use multiple distinctive tokens across the output rather than a
        # single first-50-chars substring, so leading boilerplate (license
        # headers, `ls -l` permission columns) doesn't produce false positives.
        for idx, span in enumerate(tool_call_spans):
            output = span.get("output") or ""
            if not output:
                continue
            global_idx = spans.index(span) if span in spans else -1
            subsequent = spans[global_idx + 1 :] if global_idx >= 0 else []
            if not subsequent:
                continue  # last span — nothing can reference it
            later_texts = [str(later.get("input") or "") + " " + str(later.get("output") or "") for later in subsequent]
            span_id = str(span.get("span_id") or "")
            if not _is_output_referenced(output, later_texts, span_id):
                penalties.append(
                    {
                        "event_name": "unused_tool_result",
                        "dimension": ScoringDimension.tool_efficiency,
                        "evidence": (
                            f"Tool '{span.get('name', '')}' (span {span.get('span_id', '')}) "
                            f"produced output but no subsequent span references it."
                        ),
                        "trace_event_index": idx,
                    }
                )

        return penalties

    def score_tool_failures(self, spans: list[dict]) -> list[dict]:
        """Detect tool failure penalties from spans.

        Returns list of dicts with keys: event_name, evidence, trace_event_index.
        """
        penalties: list[dict] = []
        tool_call_spans = [s for s in spans if s.get("type") == "tool_call"]

        # First pass: emit timeouts and retry_success; collect errors that still
        # need classification (so we don't double-penalize with tool_call_error
        # AND ignored_tool_failure for the same span).
        unresolved_errors: list[tuple[int, dict]] = []  # (tool_idx, span)

        for idx, span in enumerate(tool_call_spans):
            status = span.get("status", "success")
            error = span.get("error")
            latency = int(span.get("latency_ms") or 0)

            is_error = status == "error" or (error and str(error).strip())
            tool_timeout_ms = self._timeout_for(span.get("name", ""))
            is_timeout = latency > tool_timeout_ms

            if is_timeout:
                penalties.append(
                    {
                        "event_name": "tool_call_timeout",
                        "dimension": ScoringDimension.tool_failures,
                        "evidence": (
                            f"Tool '{span.get('name', '')}' (span {span.get('span_id', '')}) "
                            f"took {latency}ms, exceeding {tool_timeout_ms}ms threshold."
                        ),
                        "trace_event_index": idx,
                    }
                )
                continue

            if not is_error:
                continue

            # Retry detection: same tool name with a later SUCCESS within the
            # window counts as a retry, even if the input differs (e.g. agent
            # fixed a wrong path). This matches how humans retry — by
            # adjusting arguments, not by re-running the exact same call.
            retry_idx = _find_retry_success(tool_call_spans, idx)
            if retry_idx is not None:
                penalties.append(
                    {
                        "event_name": "tool_call_retry_success",
                        "dimension": ScoringDimension.tool_failures,
                        "evidence": (
                            f"Tool '{span.get('name', '')}' failed at index {idx} "
                            f"but succeeded on retry at index {retry_idx}."
                        ),
                        "trace_event_index": idx,
                    }
                )
                continue

            unresolved_errors.append((idx, span))

        # Second pass: classify unresolved errors as ignored_tool_failure (next
        # span is non-tool and no later retry at all) OR tool_call_error. Each
        # failure yields exactly one penalty — no double counting.
        for tool_idx, span in unresolved_errors:
            global_idx = spans.index(span) if span in spans else -1
            next_span = spans[global_idx + 1] if 0 <= global_idx < len(spans) - 1 else None
            followed_by_non_tool = next_span is not None and next_span.get("type") != "tool_call"

            if followed_by_non_tool:
                penalties.append(
                    {
                        "event_name": "ignored_tool_failure",
                        "dimension": ScoringDimension.tool_failures,
                        "evidence": (
                            f"Tool '{span.get('name', '')}' failed at span {span.get('span_id', '')}, "
                            f"but agent continued with '{next_span.get('type', '')}' span without "
                            f"retry or acknowledgment. (SLM confirmation recommended)"
                        ),
                        "trace_event_index": tool_idx,
                    }
                )
            else:
                error = span.get("error")
                status = span.get("status", "success")
                penalties.append(
                    {
                        "event_name": "tool_call_error",
                        "dimension": ScoringDimension.tool_failures,
                        "evidence": (
                            f"Tool '{span.get('name', '')}' (span {span.get('span_id', '')}) "
                            f"returned error: {str(error or status)[:200]}"
                        ),
                        "trace_event_index": tool_idx,
                    }
                )

        return penalties


def _has_state_change(spans_between: list[dict]) -> bool:
    """True if any span between two matching reads is a state-changing tool call."""
    for s in spans_between:
        if s.get("type") != "tool_call":
            continue
        name = str(s.get("name") or "")
        if _STATE_CHANGE_PATTERN.search(name):
            return True
    return False


def _find_retry_success(tool_call_spans: list[dict], error_idx: int) -> int | None:
    """Return the index of a successful same-tool-name call within the retry window.

    Accepts retries with different inputs (e.g. corrected path, fixed typo). This
    is deliberately softer than exact-hash matching so that good agent behavior
    — fail, reason, retry with adjusted args — is not double-penalized.
    """
    error_span = tool_call_spans[error_idx]
    name = error_span.get("name") or ""
    window_end = min(len(tool_call_spans), error_idx + 1 + RETRY_SPAN_WINDOW)
    for later_idx in range(error_idx + 1, window_end):
        later = tool_call_spans[later_idx]
        if (later.get("name") or "") != name:
            continue
        if later.get("status", "success") != "error" and not later.get("error"):
            return later_idx
    return None


def _span_asserts_external_state(span: dict) -> bool:
    """Heuristic: does a non-tool span contain language asserting external state?

    Looks for patterns like file paths, status claims, or data references that
    suggest the agent is stating facts about systems it did not query via tools.
    """
    text = str(span.get("input") or "") + str(span.get("output") or "")
    if not text:
        return False
    assertion_markers = [
        "the file contains",
        "the response is",
        "the output shows",
        "returns",
        "the error is",
        "the result is",
        "the status is",
        "the value is",
        "the content is",
    ]
    text_lower = text.lower()
    return any(marker in text_lower for marker in assertion_markers)


def _assertion_is_grounded(assertion_span: dict, tool_outputs: list[str]) -> bool:
    """True if the assertion text references content from at least one tool output."""
    if not tool_outputs:
        return False
    assertion_text = str(assertion_span.get("input") or "") + " " + str(assertion_span.get("output") or "")
    if not assertion_text.strip():
        return False
    for output in tool_outputs:
        tokens = _distinctive_tokens(output)
        if not tokens:
            continue
        if any(tok.lower() in assertion_text.lower() for tok in tokens):
            return True
    return False


def _is_output_referenced(output: str, later_texts: list[str], span_id: str) -> bool:
    """True if `output` is referenced by any of `later_texts` via a distinctive token or span_id."""
    if span_id:
        for t in later_texts:
            if span_id in t:
                return True
    tokens = _distinctive_tokens(output)
    if not tokens:
        # Output is all boilerplate/whitespace — treat as implicitly referenced
        # rather than penalize (there's nothing distinctive to check).
        return True
    for t in later_texts:
        t_lower = t.lower()
        for tok in tokens:
            if tok.lower() in t_lower:
                return True
    return False


def _distinctive_tokens(text: str, max_tokens: int = 8) -> list[str]:
    """Extract distinctive alphanumeric tokens, skipping common boilerplate."""
    if not text:
        return []
    result: list[str] = []
    seen: set[str] = set()
    for m in _RE_DISTINCTIVE_TOKEN.finditer(text):
        tok = m.group()
        low = tok.lower()
        if low in _BOILERPLATE_TOKENS or low in seen:
            continue
        seen.add(low)
        result.append(tok)
        if len(result) >= max_tokens:
            break
    return result


def _span_dedup_key(span: dict) -> str:
    """Generate a dedup key from tool name + input params hash."""
    name = span.get("name", "")
    input_data = span.get("input") or ""
    if isinstance(input_data, dict):
        input_data = json.dumps(input_data, sort_keys=True)
    input_hash = hashlib.md5(str(input_data).encode(), usedforsecurity=False).hexdigest()
    return f"{name}:{input_hash}"


# ---------------------------------------------------------------------------
# MatchingEngine — robust string/structural matching (BenchJack Pattern 5)
# ---------------------------------------------------------------------------

# Patterns for section header detection
_SECTION_HEADER_PATTERNS = [
    r"^##\s+{name}\s*$",  # ## Root Cause
    r"^###\s+{name}\s*$",  # ### Root Cause
    r"^\*\*{name}:?\*\*",  # **Root Cause:** or **Root Cause**
    r"^{name}\s*$",  # Root Cause (bare heading on its own line)
    r"^{name}:",  # Root Cause: ...
]


class MatchingEngine:
    """Provides robust matching for structural comparisons.

    Used by StructuralScorer for duplicate detection and output verification.
    Intentionally conservative — avoids the GAIA normalizer bug of collapsing
    semantically different strings into matches.
    """

    def are_tool_calls_duplicate(self, call_a: dict, call_b: dict, span_distance: int = 0) -> bool:
        """Determine if two tool call spans are duplicates.

        Two tool calls are duplicates if:
        1. Same tool name (exact match)
        2. Same input params (deep equality after JSON normalization)
        3. Within 5 spans of each other (larger gaps may be intentional retries)
        """
        if call_a.get("name", "") != call_b.get("name", ""):
            return False

        if span_distance > 5:
            return False

        input_a = self._normalize_json_value(call_a.get("input") or "")
        input_b = self._normalize_json_value(call_b.get("input") or "")
        return input_a == input_b

    def is_output_section_present(
        self,
        output: str,
        section_name: str,
        expected_format: str | None = None,
        all_section_contents: list[str] | None = None,
    ) -> bool:
        """Check if a required section exists in the agent's output with substantive content.

        Rules:
        1. Section header must match expected patterns
        2. Section must have >= 20 non-whitespace chars after header
        3. Section content must not be identical to another section's content
        4. If expected_format is given, verify format matches
        """
        header_pos = self._find_section_header(output, section_name)
        if header_pos < 0:
            return False

        # Extract content after header until next section or end
        content = self._extract_section_content(output, header_pos)

        # Rule 2: at least 20 non-whitespace chars
        stripped = re.sub(r"\s+", "", content)
        if len(stripped) < 20:
            return False

        # Rule 3: content must not duplicate another section
        if all_section_contents:
            normalized = self.normalize_for_comparison(content)
            for other in all_section_contents:
                if normalized == self.normalize_for_comparison(other):
                    return False

        # Rule 4: check expected format if specified
        return not (expected_format and not self._check_format(content, expected_format))

    def normalize_for_comparison(self, text: str) -> str:
        """Normalize text for comparison WITHOUT collapsing semantically different strings.

        Intentionally conservative:
        1. Lowercase
        2. Strip leading/trailing whitespace
        3. Collapse multiple spaces to single space
        4. DO NOT strip punctuation
        5. DO NOT strip numbers
        6. DO NOT strip unicode characters
        7. Preserve number formatting ("1,500" != "1500" != "15.00")
        """
        text = text.lower()
        text = text.strip()
        text = re.sub(r" {2,}", " ", text)
        return text

    def _normalize_json_value(self, value) -> str:
        """Normalize a JSON value for deep equality comparison."""
        if isinstance(value, dict):
            # Sort keys, normalize nested values, convert numbers to float
            normalized = {}
            for k in sorted(value.keys()):
                normalized[k.strip()] = self._normalize_json_value(value[k])
            return json.dumps(normalized, sort_keys=True)
        if isinstance(value, list):
            return json.dumps([self._normalize_json_value(v) for v in value])
        if isinstance(value, int | float):
            return json.dumps(float(value))
        if isinstance(value, str):
            # Try to parse as JSON dict/list
            stripped = value.strip()
            try:
                parsed = json.loads(stripped)
                if isinstance(parsed, dict | list):
                    return self._normalize_json_value(parsed)
            except (json.JSONDecodeError, ValueError):
                pass
            return stripped
        return json.dumps(value)

    def _find_section_header(self, output: str, section_name: str) -> int:
        """Find the position of a section header in output. Returns -1 if not found."""
        escaped_name = re.escape(section_name)
        for pattern_template in _SECTION_HEADER_PATTERNS:
            pattern = pattern_template.format(name=escaped_name)
            m = re.search(pattern, output, re.MULTILINE | re.IGNORECASE)
            if m:
                return m.end()
        return -1

    def _extract_section_content(self, output: str, start_pos: int) -> str:
        """Extract section content from start_pos until the next section header or end."""
        remaining = output[start_pos:]
        # Look for next section header (## or ** at start of line)
        next_header = re.search(r"^(?:#{2,}\s|\*\*[A-Z])", remaining, re.MULTILINE)
        if next_header:
            return remaining[: next_header.start()].strip()
        return remaining.strip()

    def _check_format(self, content: str, expected_format: str) -> bool:
        """Check if content matches expected format."""
        fmt = expected_format.lower()
        if fmt == "bullet list":
            return bool(re.search(r"^\s*[-*]\s", content, re.MULTILINE))
        if fmt == "paragraph":
            # At least one sentence-like string (20+ chars without list markers)
            lines = [line.strip() for line in content.split("\n") if line.strip()]
            return any(len(line) >= 20 and not line.startswith(("-", "*", "1.")) for line in lines)
        if fmt == "json":
            try:
                json.loads(content.strip())
                return True
            except (json.JSONDecodeError, ValueError):
                return False
        return True  # Unknown format — don't penalize


# ---------------------------------------------------------------------------
# NumericComparator — robust number matching (BenchJack Pattern 5)
# ---------------------------------------------------------------------------

# Regex for extracting numeric values from text
_RE_NUMBER = re.compile(
    r"(?<![a-zA-Z])"  # not preceded by a letter
    r"[$€£¥]?\s*"  # optional currency symbol
    r"(-?\d[\d,]*\.?\d*)"  # the number itself (with optional commas and decimal)
    r"\s*"
    r"(%|[KkMmBbTt](?:illion)?|[Kk]?)?"  # optional suffix
    r"(?![a-zA-Z])"  # not followed by a letter (except suffix)
)

# Multiplier suffixes
_SUFFIX_MULTIPLIERS = {
    "k": 1_000,
    "m": 1_000_000,
    "million": 1_000_000,
    "b": 1_000_000_000,
    "billion": 1_000_000_000,
    "t": 1_000_000_000_000,
    "trillion": 1_000_000_000_000,
}


class NumericComparator:
    """Robust numeric comparison for factual grounding.

    Handles currency symbols, commas, suffixes (K/M/B), and percentage/decimal
    equivalence. Never uses eval() or ast.literal_eval().
    """

    def numbers_match(self, claimed: str, source: str, tolerance: float = 0.01) -> bool:
        """Extract numbers from both strings and compare with tolerance.

        Returns True if any number from claimed matches any number from source
        within the given relative tolerance. Returns False if no numbers can
        be extracted from either string.
        """
        claimed_nums = self._extract_numbers(claimed)
        source_nums = self._extract_numbers(source)

        if not claimed_nums or not source_nums:
            return False

        for c in claimed_nums:
            for s in source_nums:
                if self._values_match(c, s, tolerance):
                    return True
        return False

    def _extract_numbers(self, text: str) -> list[float]:
        """Extract all numeric values from text, applying suffix multipliers."""
        results = []
        for match in _RE_NUMBER.finditer(text):
            raw_num = match.group(1)
            suffix = (match.group(2) or "").strip().lower()

            # Remove commas and parse
            cleaned = raw_num.replace(",", "")
            try:
                value = float(cleaned)
            except ValueError:
                continue

            # Apply suffix multiplier
            if suffix == "%":
                value = value / 100.0
            elif suffix in _SUFFIX_MULTIPLIERS:
                value = value * _SUFFIX_MULTIPLIERS[suffix]
            else:
                # Check for single-letter suffix
                suffix_key = suffix[:1] if suffix else ""
                if suffix_key in _SUFFIX_MULTIPLIERS:
                    value = value * _SUFFIX_MULTIPLIERS[suffix_key]

            results.append(value)
        return results

    def _values_match(self, a: float, b: float, tolerance: float) -> bool:
        """Compare two floats with relative tolerance."""
        if a == b == 0:
            return True
        if a == 0 or b == 0:
            return abs(a - b) <= tolerance
        relative_diff = abs(a - b) / max(abs(a), abs(b))
        return relative_diff <= tolerance
