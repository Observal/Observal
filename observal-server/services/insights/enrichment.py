"""Session data enrichment for Agent Insights.

When issue #735 (session file reconciliation) lands, this module will
check for reconciled data (thinking blocks, full tool I/O, per-turn tokens)
and merge it into session metadata for richer cost computation and
facet extraction.

Currently provides completeness scoring to indicate data quality.
"""

from __future__ import annotations


def compute_completeness(meta: dict) -> float:
    """Score how complete a session's metadata is (0.0-1.0).

    Higher scores mean more data is available for accurate analysis.
    When #735 lands, sessions with reconciled data will score > 0.9.
    """
    checks = [
        ("input_tokens", 0.15),
        ("output_tokens", 0.15),
        ("model", 0.10),
        ("stop_reason", 0.10),
        ("tool_call_count", 0.15),
        ("cache_read_tokens", 0.10),
        ("cache_write_tokens", 0.05),
        ("user_id", 0.05),
        ("platform", 0.05),
        ("duration_seconds", 0.10),
    ]
    score = 0.0
    for field, weight in checks:
        value = meta.get(field)
        if value and str(value) not in ("0", "", "None"):
            score += weight
    return round(score, 3)


def enrich_session_meta(meta: dict) -> dict:
    """Enrich a session's metadata with derived fields.

    Currently adds:
    - completeness_score: data quality indicator
    - has_errors: boolean convenience field
    - is_substantive: whether session has enough activity for facet extraction

    When #735 is available, this will also merge:
    - per_turn_tokens: token breakdown per conversation turn
    - thinking_blocks: agent reasoning content
    - full_tool_io: complete tool input/output
    - conversation_tree: full conversation structure
    """
    enriched = dict(meta)

    enriched["completeness_score"] = compute_completeness(meta)
    enriched["has_errors"] = int(meta.get("error_count", 0)) > 0
    enriched["is_substantive"] = int(meta.get("tool_call_count", 0)) >= 3 and int(meta.get("duration_seconds", 0)) >= 60

    return enriched


def enrich_all_metas(metas: dict[str, dict]) -> dict[str, dict]:
    """Enrich all session metadata in batch."""
    return {sid: enrich_session_meta(meta) for sid, meta in metas.items()}
