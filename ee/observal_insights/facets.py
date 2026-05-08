"""Session facet extraction and caching for Agent Insights.

Facets are structured metadata extracted from session transcripts via LLM analysis.
They power the qualitative sections of insight reports (friction, tool usage patterns,
user satisfaction signals).
"""

from __future__ import annotations

from datetime import UTC, datetime

import structlog

from ._deps import get_call_model, get_facets_model, get_settings

logger = structlog.get_logger(__name__)

FACET_EXTRACTION_PROMPT = """Analyze this AI coding agent session transcript and extract structured facets.

## Session Metadata
- Session ID: {session_id}
- Duration: {duration_seconds}s
- Tool calls: {tool_call_count}
- Errors: {error_count}
- Model: {model}

## Transcript
{transcript}

Extract the following facets as a JSON object:
{{
  "task_type": "<one of: debugging | feature_implementation | refactoring | exploration | configuration | testing | documentation | code_review | unknown>",
  "complexity": "<low | medium | high>",
  "outcome": "<success | partial | failure | abandoned>",
  "friction_points": [
    {{"type": "<error_recovery | tool_failure | context_loss | misunderstanding | slow_response>", "description": "<brief description>"}}
  ],
  "tools_effective": ["<tool names that worked well>"],
  "tools_problematic": ["<tool names that caused issues>"],
  "user_satisfaction_signals": {{
    "interruptions": <number of user interruptions>,
    "retries": <number of retry attempts>,
    "sentiment": "<positive | neutral | negative | unknown>"
  }},
  "notable_patterns": ["<any interesting patterns worth noting>"]
}}

Rules:
- Base everything on the transcript evidence
- If insufficient data, use "unknown" values
- Maximum 3 friction points
- Maximum 3 notable patterns"""


async def extract_facets(
    session_id: str,
    transcript: str,
    meta: dict,
) -> dict:
    """Extract structured facets from a session transcript using an LLM.

    Args:
        session_id: The session identifier.
        transcript: Formatted session transcript text.
        meta: Session metadata dict (duration_seconds, tool_call_count, etc.).

    Returns:
        Dict of extracted facets, or empty dict on failure.
    """
    if not transcript or len(transcript.strip()) < 50:
        logger.debug("facets_skip_short_transcript", session_id=session_id)
        return {}

    call_model = get_call_model()
    settings = get_settings()

    model_override = getattr(settings, "INSIGHT_MODEL_FACETS", None) or None

    prompt = FACET_EXTRACTION_PROMPT.format(
        session_id=session_id,
        duration_seconds=meta.get("duration_seconds", 0),
        tool_call_count=meta.get("tool_call_count", 0),
        error_count=meta.get("error_count", 0),
        model=meta.get("model", "unknown"),
        transcript=transcript,
    )

    try:
        result = await call_model(prompt, model_override=model_override, max_tokens=4096)
        if result and isinstance(result, dict):
            return result
        logger.warning("facets_empty_response", session_id=session_id)
        return {}
    except Exception as e:
        logger.error("facets_extraction_failed", session_id=session_id, error=str(e))
        return {}


async def load_cached_facets(
    session_id: str,
    db,
) -> dict | None:
    """Load previously extracted facets from the database.

    Args:
        session_id: The session to look up.
        db: An AsyncSession instance.

    Returns:
        Facets dict if cached, None otherwise.
    """
    FacetsModel = get_facets_model()

    from sqlalchemy import select

    stmt = select(FacetsModel).where(FacetsModel.session_id == session_id)
    result = await db.execute(stmt)
    row = result.scalar_one_or_none()

    if row is None:
        return None

    return row.facets if hasattr(row, "facets") else None


async def store_facets(
    session_id: str,
    agent_id: str,
    facets: dict,
    db,
) -> None:
    """Persist extracted facets to the database.

    Args:
        session_id: The session identifier.
        agent_id: The agent UUID (as string).
        facets: The extracted facets dict.
        db: An AsyncSession instance.
    """
    FacetsModel = get_facets_model()

    from sqlalchemy import select

    # Check if already exists (unique on agent_id + session_id)
    stmt = (
        select(FacetsModel)
        .where(FacetsModel.agent_id == agent_id)
        .where(FacetsModel.session_id == session_id)
    )
    result = await db.execute(stmt)
    existing = result.scalar_one_or_none()

    if existing:
        existing.facets = facets
        existing.extracted_at = datetime.now(UTC)
    else:
        record = FacetsModel(
            session_id=session_id,
            agent_id=agent_id,
            facets=facets,
            extracted_at=datetime.now(UTC),
        )
        db.add(record)

    await db.flush()


async def extract_and_cache_facets(
    session_id: str,
    transcript: str,
    meta: dict,
    agent_id: str,
    db,
) -> dict:
    """Extract facets for a session, using cache when available.

    Checks the database first; if not cached, extracts via LLM and stores.

    Args:
        session_id: The session identifier.
        transcript: Session transcript text.
        meta: Session metadata dict.
        agent_id: The agent UUID (as string).
        db: An AsyncSession instance.

    Returns:
        Extracted facets dict.
    """
    # Check cache first
    cached = await load_cached_facets(session_id, db)
    if cached:
        logger.debug("facets_cache_hit", session_id=session_id)
        return cached

    # Extract fresh
    facets = await extract_facets(session_id, transcript, meta)
    if facets:
        await store_facets(session_id, agent_id, facets, db)
        logger.debug("facets_extracted_and_cached", session_id=session_id)

    return facets


def aggregate_facets(all_facets: list[dict]) -> dict:
    """Aggregate facets across multiple sessions into summary statistics.

    Args:
        all_facets: List of per-session facet dicts.

    Returns:
        Aggregated summary suitable for inclusion in the report data block.
    """
    if not all_facets:
        return {}

    task_types: dict[str, int] = {}
    outcomes: dict[str, int] = {}
    friction_types: dict[str, int] = {}
    tools_effective: dict[str, int] = {}
    tools_problematic: dict[str, int] = {}
    total_interruptions = 0
    total_retries = 0
    sentiments: dict[str, int] = {}
    complexities: dict[str, int] = {}

    for f in all_facets:
        if not f:
            continue

        # Task types
        tt = f.get("task_type", "unknown")
        task_types[tt] = task_types.get(tt, 0) + 1

        # Complexity
        cx = f.get("complexity", "unknown")
        complexities[cx] = complexities.get(cx, 0) + 1

        # Outcomes
        oc = f.get("outcome", "unknown")
        outcomes[oc] = outcomes.get(oc, 0) + 1

        # Friction points
        for fp in f.get("friction_points", []):
            ft = fp.get("type", "unknown")
            friction_types[ft] = friction_types.get(ft, 0) + 1

        # Tools
        for tool in f.get("tools_effective", []):
            tools_effective[tool] = tools_effective.get(tool, 0) + 1
        for tool in f.get("tools_problematic", []):
            tools_problematic[tool] = tools_problematic.get(tool, 0) + 1

        # Satisfaction signals
        signals = f.get("user_satisfaction_signals", {})
        total_interruptions += int(signals.get("interruptions", 0))
        total_retries += int(signals.get("retries", 0))
        sent = signals.get("sentiment", "unknown")
        sentiments[sent] = sentiments.get(sent, 0) + 1

    n = len(all_facets)
    return {
        "sessions_with_facets": n,
        "task_types": sorted(task_types.items(), key=lambda x: -x[1]),
        "complexity_distribution": complexities,
        "outcomes": outcomes,
        "friction_types": sorted(friction_types.items(), key=lambda x: -x[1]),
        "tools_effective": sorted(tools_effective.items(), key=lambda x: -x[1])[:10],
        "tools_problematic": sorted(tools_problematic.items(), key=lambda x: -x[1])[:10],
        "satisfaction": {
            "total_interruptions": total_interruptions,
            "total_retries": total_retries,
            "avg_interruptions_per_session": round(total_interruptions / n, 2) if n else 0,
            "sentiment_distribution": sentiments,
        },
    }
