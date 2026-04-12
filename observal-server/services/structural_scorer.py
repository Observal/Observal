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

# Timeout threshold in ms for tool calls
DEFAULT_TIMEOUT_MS = 30_000


class StructuralScorer:
    """Rule-based scorer for tool_efficiency and tool_failures dimensions."""

    def __init__(self, timeout_ms: int = DEFAULT_TIMEOUT_MS):
        self.timeout_ms = timeout_ms

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

        # Ungrounded claims: agent asserts external state (e.g. file contents,
        # API responses) without any tool call providing that information.
        # Detected when non-tool spans contain assertion patterns but the trace
        # has zero tool calls to back them up.
        if len(tool_call_spans) == 0 and len(non_tool_spans) > 0:
            has_assertions = any(_span_asserts_external_state(s) for s in non_tool_spans)
            if has_assertions:
                penalties.append(
                    {
                        "event_name": "ungrounded_claims",
                        "dimension": ScoringDimension.tool_efficiency,
                        "evidence": (
                            f"Agent {agent_id} made assertions about external state "
                            f"but trace contains 0 tool call spans to ground them."
                        ),
                        "trace_event_index": None,
                    }
                )
                return penalties

        # Duplicate tool calls: same tool name + same input hash
        seen: dict[str, int] = {}
        for idx, span in enumerate(tool_call_spans):
            key = _span_dedup_key(span)
            if key in seen:
                penalties.append(
                    {
                        "event_name": "duplicate_tool_call",
                        "dimension": ScoringDimension.tool_efficiency,
                        "evidence": (
                            f"Duplicate call to '{span.get('name', '')}' with same params. "
                            f"First at index {seen[key]}, duplicate at index {idx}."
                        ),
                        "trace_event_index": idx,
                    }
                )
            else:
                seen[key] = idx

        # Unused tool results: tool output not referenced by any subsequent span.
        # Each unused call is penalized individually rather than comparing against
        # an arbitrary median, so the penalty scales with actual waste.
        for idx, span in enumerate(tool_call_spans):
            output = span.get("output") or ""
            if not output:
                continue
            global_idx = spans.index(span) if span in spans else -1
            subsequent = spans[global_idx + 1 :] if global_idx >= 0 else []
            if not subsequent:
                continue  # last span — nothing can reference it
            referenced = False
            for later in subsequent:
                later_input = later.get("input") or ""
                if output[:50] in later_input:
                    referenced = True
                    break
            if not referenced:
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

        failed_spans: list[tuple[int, dict]] = []
        for idx, span in enumerate(tool_call_spans):
            status = span.get("status", "success")
            error = span.get("error")
            latency = int(span.get("latency_ms") or 0)

            is_error = status == "error" or (error and str(error).strip())
            is_timeout = latency > self.timeout_ms

            if is_error or is_timeout:
                failed_spans.append((idx, span))

            # Timeout detection
            if is_timeout:
                penalties.append(
                    {
                        "event_name": "tool_call_timeout",
                        "dimension": ScoringDimension.tool_failures,
                        "evidence": (
                            f"Tool '{span.get('name', '')}' (span {span.get('span_id', '')}) "
                            f"took {latency}ms, exceeding {self.timeout_ms}ms threshold."
                        ),
                        "trace_event_index": idx,
                    }
                )
            elif is_error:
                # Check for retry success
                key = _span_dedup_key(span)
                retried = False
                for later_idx, later_span in enumerate(tool_call_spans[idx + 1 :], idx + 1):
                    if _span_dedup_key(later_span) == key:
                        later_status = later_span.get("status", "success")
                        if later_status != "error" and not later_span.get("error"):
                            retried = True
                            penalties.append(
                                {
                                    "event_name": "tool_call_retry_success",
                                    "dimension": ScoringDimension.tool_failures,
                                    "evidence": (
                                        f"Tool '{span.get('name', '')}' failed at index {idx} "
                                        f"but succeeded on retry at index {later_idx}."
                                    ),
                                    "trace_event_index": idx,
                                }
                            )
                            break
                if not retried:
                    penalties.append(
                        {
                            "event_name": "tool_call_error",
                            "dimension": ScoringDimension.tool_failures,
                            "evidence": (
                                f"Tool '{span.get('name', '')}' (span {span.get('span_id', '')}) "
                                f"returned error: {str(error or status)[:200]}"
                            ),
                            "trace_event_index": idx,
                        }
                    )

        # Ignored tool failure: error span followed by non-tool span
        # (candidate for SLM confirmation)
        for idx, span in failed_spans:
            global_idx = spans.index(span) if span in spans else -1
            if global_idx < 0 or global_idx >= len(spans) - 1:
                continue
            next_span = spans[global_idx + 1]
            if next_span.get("type") != "tool_call":
                key = _span_dedup_key(span)
                # Check no retry anywhere later
                has_retry = any(
                    _span_dedup_key(s) == key
                    for s in tool_call_spans[tool_call_spans.index(span) + 1 :]
                    if s is not span
                )
                if not has_retry:
                    penalties.append(
                        {
                            "event_name": "ignored_tool_failure",
                            "dimension": ScoringDimension.tool_failures,
                            "evidence": (
                                f"Tool '{span.get('name', '')}' failed at span {span.get('span_id', '')}, "
                                f"but agent continued with '{next_span.get('type', '')}' span without "
                                f"retry or acknowledgment. (SLM confirmation recommended)"
                            ),
                            "trace_event_index": idx,
                        }
                    )

        return penalties


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


def _span_dedup_key(span: dict) -> str:
    """Generate a dedup key from tool name + input params hash."""
    name = span.get("name", "")
    input_data = span.get("input") or ""
    if isinstance(input_data, dict):
        input_data = json.dumps(input_data, sort_keys=True)
    input_hash = hashlib.md5(str(input_data).encode()).hexdigest()
    return f"{name}:{input_hash}"


# ---------------------------------------------------------------------------
# MatchingEngine — robust string/structural matching (BenchJack Pattern 5)
# ---------------------------------------------------------------------------

# Patterns for section header detection
_SECTION_HEADER_PATTERNS = [
    r"^##\s+{name}\s*$",         # ## Root Cause
    r"^###\s+{name}\s*$",        # ### Root Cause
    r"^\*\*{name}:?\*\*",        # **Root Cause:** or **Root Cause**
    r"^{name}\s*$",              # Root Cause (bare heading on its own line)
    r"^{name}:",                 # Root Cause: ...
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
        if isinstance(value, (int, float)):
            return json.dumps(float(value))
        if isinstance(value, str):
            # Try to parse as JSON dict/list
            stripped = value.strip()
            try:
                parsed = json.loads(stripped)
                if isinstance(parsed, (dict, list)):
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
    r"(?<![a-zA-Z])"          # not preceded by a letter
    r"[$€£¥]?\s*"             # optional currency symbol
    r"(-?\d[\d,]*\.?\d*)"     # the number itself (with optional commas and decimal)
    r"\s*"
    r"(%|[KkMmBbTt](?:illion)?|[Kk]?)?"  # optional suffix
    r"(?![a-zA-Z])"           # not followed by a letter (except suffix)
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
