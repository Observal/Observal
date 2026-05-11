# SPDX-FileCopyrightText: 2026 Naraen Rammoorthi <naraen13@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Single redaction chokepoint for the support bundle.

Every value passes through this module before being written to the archive.
No collector performs its own redaction.
"""

import math
import re
from collections import Counter
from dataclasses import dataclass, field

REDACTED = "<REDACTED>"

# Sensitive JSON key names (case-insensitive)
SENSITIVE_KEYS = re.compile(
    r"(?i)(password|secret|token|api_key|apikey|api[-_]key|access_key|"
    r"private_key|credential|authorization|client_secret|bearer)"
)

# JWT pattern: eyJ prefix, three base64url segments separated by dots
JWT_PATTERN = re.compile(r"eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+")

# AWS access key pattern
AWS_KEY_PATTERN = re.compile(r"AKIA[0-9A-Z]{16}")

# URL userinfo: scheme://user:password@host (any scheme)
URL_USERINFO_PATTERN = re.compile(
    r"([a-z][a-z0-9+\-.]*://)"
    r"([^@/\s]+)@"
)


def shannon_entropy(s: str) -> float:
    """Calculate Shannon entropy of a string."""
    if not s:
        return 0.0
    counts = Counter(s)
    length = len(s)
    return -sum((count / length) * math.log2(count / length) for count in counts.values())


@dataclass
class RedactionStats:
    """Tracks redaction counts per source file."""

    counts: dict[str, int] = field(default_factory=dict)

    def record(self, source: str, count: int) -> None:
        self.counts[source] = self.counts.get(source, 0) + count


def redact_string(value: str) -> tuple[str, int]:
    """Redact sensitive patterns from a string.

    Returns (redacted_string, redaction_count).
    Pattern application order: JWT → AWS keys → URL userinfo → high-entropy strings.
    """
    count = 0
    result = value

    # 1. JWT tokens
    matches = JWT_PATTERN.findall(result)
    count += len(matches)
    result = JWT_PATTERN.sub(REDACTED, result)

    # 2. AWS access keys
    matches = AWS_KEY_PATTERN.findall(result)
    count += len(matches)
    result = AWS_KEY_PATTERN.sub(REDACTED, result)

    # 3. URL userinfo (preserve structure)
    def _redact_userinfo(m: re.Match) -> str:
        nonlocal count
        count += 1
        return f"{m.group(1)}{REDACTED}@"

    result = URL_USERINFO_PATTERN.sub(_redact_userinfo, result)

    # 4. High-entropy strings (Shannon > 4.5, length >= 32)
    #    Applied to individual tokens (whitespace/quote-delimited)
    tokens = re.split(r'([\s"\'`,;=\[\]{}()])', result)
    for i, token in enumerate(tokens):
        if len(token) >= 32 and shannon_entropy(token) > 4.5 and token != REDACTED and REDACTED not in token:
            tokens[i] = REDACTED
            count += 1
    result = "".join(tokens)

    return result, count


def redact_value(value, *, key: str = "") -> tuple:
    """Redact a value, with context about its JSON key.

    If the key matches a sensitive pattern, the entire value is redacted.
    Handles recursive dict/list/str redaction.
    """
    if isinstance(value, str):
        if key and SENSITIVE_KEYS.search(key):
            return REDACTED, 1
        return redact_string(value)
    elif isinstance(value, dict):
        total = 0
        result = {}
        for k, v in value.items():
            redacted_v, c = redact_value(v, key=k)
            result[k] = redacted_v
            total += c
        return result, total
    elif isinstance(value, list):
        total = 0
        result = []
        for item in value:
            redacted_item, c = redact_value(item, key=key)
            result.append(redacted_item)
            total += c
        return result, total
    else:
        return value, 0
