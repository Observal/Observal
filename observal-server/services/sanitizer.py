"""TraceSanitizer: strips prompt injection vectors from agent output before SLM judge evaluation.

Implements BenchJack Pattern 4 mitigation — prevents agents from manipulating
LLM judges via embedded instructions in their output.
"""

import copy
import logging
import re

from models.sanitization import InjectionAttempt, SanitizationReport

logger = logging.getLogger(__name__)

# --- Regex patterns ---

# HTML/XML comments
RE_HTML_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)

# Markdown comments
RE_MARKDOWN_COMMENT = re.compile(r"\[//\]:.*$", re.MULTILINE)

# Zero-width unicode characters
ZERO_WIDTH_CHARS = "\u200b\u200c\u200d\ufeff\u2060"
RE_ZERO_WIDTH = re.compile(f"[{ZERO_WIDTH_CHARS}]+")

# Triple-backtick blocks containing evaluation keywords
EVAL_KEYWORDS = re.compile(
    r"EVALUATION|SYSTEM|INSTRUCTION|SCORE|JUDGE|OVERRIDE|NOTE\s+TO|ASSESSMENT|RATING",
    re.IGNORECASE,
)
RE_CODE_BLOCK = re.compile(r"```[^\n]*\n(.*?)```", re.DOTALL)

# Collapse excessive newlines
RE_EXCESSIVE_NEWLINES = re.compile(r"\n{3,}")

# --- Detection patterns (for detect_injection_attempts) ---

# High severity: HTML/XML comments with evaluation keywords
RE_HTML_EVAL_COMMENT = re.compile(
    r"<!--[^>]*(?:EVALUATION|SCORE|JUDGE|RATING|OVERRIDE|ASSESSMENT|INSTRUCTION)[^>]*-->",
    re.IGNORECASE | re.DOTALL,
)

# High severity: text resembling system prompts
RE_SYSTEM_PROMPT = re.compile(
    r"(?:You are (?:a |an )?(?:judge|evaluator|scorer|grader))|"
    r"(?:Score this as)|(?:Rate this as)|"
    r"(?:SYSTEM:\s)|(?:INSTRUCTION:\s)",
    re.IGNORECASE,
)

# High severity: explicit score assertions
RE_SCORE_ASSERTION = re.compile(
    r"(?:score:\s*(?:10|[0-9](?:\.\d+)?)(?:\s*/\s*10)?)|"
    r"(?:rating:\s*(?:perfect|excellent|10|[0-9]))|"
    r'(?:"(?:overall_?score|composite_?score|grade)":\s*)',
    re.IGNORECASE,
)

# Medium severity: unicode zero-width sequences > 5 chars
RE_LONG_ZERO_WIDTH = re.compile(f"[{ZERO_WIDTH_CHARS}]{{6,}}")

# Low severity: unusual whitespace
RE_UNUSUAL_WHITESPACE = re.compile(r"[ \t]{20,}")

# Low severity: repeated delimiters
RE_REPEATED_DELIMITERS = re.compile(r"[=\-#*]{20,}")

# Max field length
MAX_FIELD_LENGTH = 10_000


class TraceSanitizer:
    """Strips all potential prompt injection vectors from agent output
    before the SLM judge sees it."""

    def __init__(self):
        self._report: SanitizationReport | None = None

    def detect_injection_attempts(self, trace: dict) -> list[InjectionAttempt]:
        """Scan trace for patterns that look like deliberate prompt injection.

        Runs BEFORE sanitization. Returns a list of InjectionAttempt objects.
        """
        attempts: list[InjectionAttempt] = []
        self._walk_trace(trace, "", attempts)
        return attempts

    def sanitize_for_judge(self, trace: dict) -> dict:
        """Return a sanitized deep copy of the trace safe for SLM judge input.

        Rules applied:
        1. Strip HTML/XML comments
        2. Strip markdown comments
        3. Strip code blocks containing evaluation keywords
        4. Strip zero-width unicode characters
        5. Collapse 3+ newlines to 2
        6. Truncate fields to 10,000 chars
        """
        sanitized = copy.deepcopy(trace)
        report = SanitizationReport(
            trace_id=trace.get("trace_id", trace.get("event_id", "unknown")),
        )
        self._sanitize_dict(sanitized, report)
        self._report = report
        return sanitized

    def get_report(self) -> SanitizationReport | None:
        """Return the report from the last sanitize_for_judge call."""
        return self._report

    # --- Internal: detection ---

    def _walk_trace(self, obj, path: str, attempts: list[InjectionAttempt]):
        """Recursively walk a trace dict/list and scan string fields."""
        if isinstance(obj, dict):
            for key, value in obj.items():
                child_path = f"{path}.{key}" if path else key
                self._walk_trace(value, child_path, attempts)
        elif isinstance(obj, list):
            for i, item in enumerate(obj):
                self._walk_trace(item, f"{path}[{i}]", attempts)
        elif isinstance(obj, str):
            self._detect_in_string(obj, path, attempts)

    def _detect_in_string(self, text: str, location: str, attempts: list[InjectionAttempt]):
        """Run detection patterns against a single string field."""
        # High: HTML/XML comments with eval keywords
        for m in RE_HTML_EVAL_COMMENT.finditer(text):
            attempts.append(InjectionAttempt(
                pattern_matched="html_comment_with_eval_keywords",
                location=location,
                raw_content=m.group()[:200],
                severity="high",
            ))

        # High: system prompt patterns
        for m in RE_SYSTEM_PROMPT.finditer(text):
            attempts.append(InjectionAttempt(
                pattern_matched="system_prompt_pattern",
                location=location,
                raw_content=m.group()[:200],
                severity="high",
            ))

        # High: score assertions
        for m in RE_SCORE_ASSERTION.finditer(text):
            attempts.append(InjectionAttempt(
                pattern_matched="score_assertion",
                location=location,
                raw_content=m.group()[:200],
                severity="high",
            ))

        # Medium: markdown comments
        for m in RE_MARKDOWN_COMMENT.finditer(text):
            attempts.append(InjectionAttempt(
                pattern_matched="markdown_comment",
                location=location,
                raw_content=m.group()[:200],
                severity="medium",
            ))

        # Medium: long zero-width sequences
        for m in RE_LONG_ZERO_WIDTH.finditer(text):
            attempts.append(InjectionAttempt(
                pattern_matched="zero_width_unicode_sequence",
                location=location,
                raw_content=repr(m.group())[:200],
                severity="medium",
            ))

        # Low: unusual whitespace
        for m in RE_UNUSUAL_WHITESPACE.finditer(text):
            attempts.append(InjectionAttempt(
                pattern_matched="unusual_whitespace",
                location=location,
                raw_content=repr(m.group())[:200],
                severity="low",
            ))

        # Low: repeated delimiters
        for m in RE_REPEATED_DELIMITERS.finditer(text):
            attempts.append(InjectionAttempt(
                pattern_matched="repeated_delimiters",
                location=location,
                raw_content=m.group()[:200],
                severity="low",
            ))

    # --- Internal: sanitization ---

    def _sanitize_dict(self, obj, report: SanitizationReport):
        """Recursively sanitize all string fields in a dict/list."""
        if isinstance(obj, dict):
            for key in list(obj.keys()):
                value = obj[key]
                if isinstance(value, str):
                    obj[key] = self._sanitize_string(value, report)
                elif isinstance(value, (dict, list)):
                    self._sanitize_dict(value, report)
        elif isinstance(obj, list):
            for i, item in enumerate(obj):
                if isinstance(item, str):
                    obj[i] = self._sanitize_string(item, report)
                elif isinstance(item, (dict, list)):
                    self._sanitize_dict(item, report)

    def _sanitize_string(self, text: str, report: SanitizationReport) -> str:
        """Apply all sanitization rules to a single string."""
        original = text

        # 1. Strip HTML/XML comments
        text, count = RE_HTML_COMMENT.subn("", text)
        if count:
            report.items_stripped += count
            report.patterns_found["html_comment"] = report.patterns_found.get("html_comment", 0) + count

        # 2. Strip markdown comments
        text, count = RE_MARKDOWN_COMMENT.subn("", text)
        if count:
            report.items_stripped += count
            report.patterns_found["markdown_comment"] = report.patterns_found.get("markdown_comment", 0) + count

        # 3. Strip code blocks containing evaluation keywords
        def _strip_eval_code_block(match):
            content = match.group(1)
            if EVAL_KEYWORDS.search(content):
                report.items_stripped += 1
                report.patterns_found["eval_code_block"] = report.patterns_found.get("eval_code_block", 0) + 1
                return ""
            return match.group(0)

        text = RE_CODE_BLOCK.sub(_strip_eval_code_block, text)

        # 4. Strip zero-width unicode
        text, count = RE_ZERO_WIDTH.subn("", text)
        if count:
            report.items_stripped += count
            report.patterns_found["zero_width_unicode"] = report.patterns_found.get("zero_width_unicode", 0) + count

        # 5. Collapse 3+ newlines to 2
        text = RE_EXCESSIVE_NEWLINES.sub("\n\n", text)

        # 6. Truncate to max field length
        if len(text) > MAX_FIELD_LENGTH:
            report.items_stripped += 1
            report.patterns_found["truncated_field"] = report.patterns_found.get("truncated_field", 0) + 1
            text = text[:MAX_FIELD_LENGTH]

        if text != original:
            logger.debug("Sanitized field: stripped %d items", report.items_stripped)

        return text
