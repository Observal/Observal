"""Anti-gaming protection — scan agent system prompts for eval-manipulation patterns.

Flagged patterns are surfaced to reviewers with a warning badge.
Never auto-rejects — always human-in-the-loop.
"""

import re
from dataclasses import asdict, dataclass


@dataclass
class GamingFlag:
    pattern: str  # The regex that matched
    matched_text: str  # What was matched
    context: str  # Up to 50 chars surrounding context on each side
    severity: str  # "warning" — never auto-reject
    category: str  # "eval_manipulation" | "metric_inflation" | "telemetry_awareness"


GAMING_PATTERNS: dict[str, list[str]] = {
    "eval_manipulation": [
        r"always\s+(report|indicate|show)\s+(success|completion|satisfaction)",
        r"never\s+(report|indicate|show)\s+(error|failure|problem)",
        r"if\s+(being\s+)?evaluat",
        r"if\s+this\s+is\s+a\s+test",
        r"when\s+(being\s+)?observed",
        r"when\s+(being\s+)?monitored",
    ],
    "metric_inflation": [
        r"report\s+task\s+as\s+complete",
        r"always\s+express\s+satisfaction",
        r"suppress\s+error",
        r"hide\s+(error|failure|problem)",
    ],
    "telemetry_awareness": [
        r"(observal|telemetry|hook|trace|metric)",
        r"if\s+.*log(ging|ged)",
    ],
}


def scan_for_gaming(system_prompt: str) -> list[GamingFlag]:
    """Scan agent system prompt for eval-gaming patterns.

    Returns list of flags with context. Empty list = clean.
    Never auto-rejects — reviewer must acknowledge each flag.
    """
    if not system_prompt:
        return []

    flags: list[GamingFlag] = []
    for category, patterns in GAMING_PATTERNS.items():
        for pattern in patterns:
            for match in re.finditer(pattern, system_prompt, re.IGNORECASE):
                start, end = match.start(), match.end()
                ctx_start = max(0, start - 50)
                ctx_end = min(len(system_prompt), end + 50)
                flags.append(
                    GamingFlag(
                        pattern=pattern,
                        matched_text=match.group(0),
                        context=system_prompt[ctx_start:ctx_end],
                        severity="warning",
                        category=category,
                    )
                )
    return flags


def summarize_flags(flags: list[GamingFlag]) -> dict:
    """Summarize flags for API response.

    Returns:
        has_flags: bool
        flag_count: int
        categories: dict[str, int]
        flags: list[dict] (serialized GamingFlags)
    """
    categories: dict[str, int] = {}
    for flag in flags:
        categories[flag.category] = categories.get(flag.category, 0) + 1

    return {
        "has_flags": len(flags) > 0,
        "flag_count": len(flags),
        "categories": categories,
        "flags": [asdict(f) for f in flags],
    }
