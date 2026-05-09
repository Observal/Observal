"""Session facet extraction and caching for Agent Insights (V3).

Facets are structured metadata extracted from session transcripts via LLM analysis.
They power the qualitative sections of insight reports (friction, tool usage patterns,
user satisfaction signals, goal categorisation, and repeated-instruction detection).

V3 uses the full Claude Code taxonomy with expanded goal categories, friction types,
outcome granularity, and new dimensions (helpfulness, session_type, repeated_instructions).
"""

from __future__ import annotations

from datetime import UTC, datetime

import structlog

from ._deps import get_call_model, get_facets_model, get_settings

logger = structlog.get_logger(__name__)

FACET_EXTRACTION_PROMPT = """\
Analyze this AI coding agent session transcript and extract structured facets.

## Session Metadata
- Session ID: {session_id}
- Duration: {duration_seconds}s
- Tool calls: {tool_call_count}
- Prompts: {prompt_count}
- IDE: {ide}

## Transcript
{transcript}

Extract the following as a JSON object. Base everything on transcript evidence.

{{
  "underlying_goal": "<what the user fundamentally wanted to accomplish>",
  "goal_categories": ["<from: debug_investigate, implement_feature, fix_bug, write_script_tool, refactor_code, configure_system, create_pr_commit, analyze_data, understand_codebase, write_tests, write_docs, deploy_infra, warmup_minimal>"],
  "outcome": "<fully_achieved | mostly_achieved | partially_achieved | not_achieved | unclear>",
  "user_satisfaction": "<frustrated | dissatisfied | likely_satisfied | satisfied | happy | unsure>",
  "agent_helpfulness": "<unhelpful | slightly_helpful | moderately_helpful | very_helpful | essential>",
  "session_type": "<single_task | multi_task | iterative_refinement | exploration | quick_question>",
  "complexity": "<trivial | low | medium | high | very_high>",
  "friction_points": [
    {{
      "type": "<from: misunderstood_request, wrong_approach, buggy_code, user_rejected_action, agent_got_blocked, user_stopped_early, wrong_file_or_location, excessive_changes, slow_or_verbose, tool_failed, user_unclear, external_issue>",
      "description": "<specific description of what happened>",
      "severity": "<blocking | major | minor>"
    }}
  ],
  "primary_success_factors": ["<from: fast_accurate_search, correct_code_edits, good_explanations, proactive_help, multi_file_changes, good_debugging>"],
  "tools_effective": ["<tool names that worked well>"],
  "tools_problematic": [{{"tool": "<name>", "reason": "<why it was problematic>"}}],
  "repeated_instructions": ["<instructions the user frequently repeats to the agent>"],
  "notable_patterns": ["<interesting observations>"],
  "brief_summary": "<one-sentence session summary>"
}}

Rules:
- Base everything on transcript evidence, not assumptions
- If insufficient data for a field, use "unclear" or empty arrays
- Maximum 5 friction_points
- Maximum 5 notable_patterns
- Maximum 5 repeated_instructions
- goal_categories can have 1-3 entries
- primary_success_factors can have 0-3 entries"""


async def extract_facets(
    session_id: str,
    transcript: str,
    meta: dict,
) -> dict:
    """Extract structured facets from a session transcript using an LLM.

    Args:
        session_id: The session identifier.
        transcript: Formatted session transcript text.
        meta: Session metadata dict (duration_seconds, tool_call_count, prompt_count, ide, etc.).

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
        prompt_count=meta.get("prompt_count", 0),
        ide=meta.get("ide", "unknown"),
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

    # Check if already exists
    stmt = select(FacetsModel).where(FacetsModel.session_id == session_id)
    result = await db.execute(stmt)
    existing = result.scalar_one_or_none()

    if existing:
        existing.facets = facets
        existing.updated_at = datetime.now(UTC)
    else:
        record = FacetsModel(
            session_id=session_id,
            agent_id=agent_id,
            facets=facets,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        db.add(record)

    await db.flush()


async def should_re_extract(session_id: str, db) -> bool:
    """Check if cached facets are stale because the session continued.

    Compares the facets record's updated_at timestamp against the session's
    last event time from ClickHouse to determine if re-extraction is needed.

    Args:
        session_id: The session identifier.
        db: An AsyncSession instance.

    Returns:
        True if facets should be re-extracted, False if cache is still valid.
    """
    cached = await load_cached_facets(session_id, db)
    if cached is None:
        return True  # No cache -> must extract

    # Get the cached record's updated_at timestamp
    FacetsModel = get_facets_model()
    from sqlalchemy import select

    stmt = select(FacetsModel).where(FacetsModel.session_id == session_id)
    result = await db.execute(stmt)
    row = result.scalar_one_or_none()
    if row is None:
        return True

    facets_updated_at = row.updated_at

    # Check if session has newer events
    from .session_cache import get_session_last_event_time

    session_last_event = await get_session_last_event_time(session_id)

    if session_last_event is None:
        return False  # Can't determine, use cached

    return session_last_event > facets_updated_at


async def extract_and_cache_facets(
    session_id: str,
    transcript: str,
    meta: dict,
    agent_id: str,
    db,
) -> dict:
    """Extract facets for a session, with staleness-aware caching.

    Checks whether cached facets are stale (session continued since last
    extraction). If not stale, returns cached facets. Otherwise, extracts
    fresh facets via LLM and stores them.

    Args:
        session_id: The session identifier.
        transcript: Session transcript text.
        meta: Session metadata dict.
        agent_id: The agent UUID (as string).
        db: An AsyncSession instance.

    Returns:
        Extracted facets dict.
    """
    # Check cache with staleness
    stale = await should_re_extract(session_id, db)
    if not stale:
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
    """Aggregate V3 facets across multiple sessions into summary statistics.

    Processes the expanded V3 taxonomy including goal categories, satisfaction,
    helpfulness, session types, and repeated instructions.

    Args:
        all_facets: List of per-session facet dicts.

    Returns:
        Aggregated summary suitable for inclusion in the report data block.
    """
    if not all_facets:
        return {}

    goal_categories: dict[str, int] = {}
    outcomes: dict[str, int] = {}
    satisfaction: dict[str, int] = {}
    helpfulness: dict[str, int] = {}
    session_types: dict[str, int] = {}
    friction_types: dict[str, int] = {}
    success_factors: dict[str, int] = {}
    tools_effective: dict[str, int] = {}
    tools_problematic: dict[str, int] = {}
    complexities: dict[str, int] = {}
    repeated_instructions_all: list[str] = []

    for f in all_facets:
        if not f:
            continue

        # Goal categories (list)
        for cat in f.get("goal_categories", []):
            goal_categories[cat] = goal_categories.get(cat, 0) + 1

        # Outcome
        oc = f.get("outcome", "unclear")
        outcomes[oc] = outcomes.get(oc, 0) + 1

        # Satisfaction
        sat = f.get("user_satisfaction", "unsure")
        satisfaction[sat] = satisfaction.get(sat, 0) + 1

        # Helpfulness
        hlp = f.get("agent_helpfulness", "moderately_helpful")
        helpfulness[hlp] = helpfulness.get(hlp, 0) + 1

        # Session type
        st = f.get("session_type", "single_task")
        session_types[st] = session_types.get(st, 0) + 1

        # Complexity
        cx = f.get("complexity", "medium")
        complexities[cx] = complexities.get(cx, 0) + 1

        # Friction
        for fp in f.get("friction_points", []):
            ft = fp.get("type", "unknown")
            friction_types[ft] = friction_types.get(ft, 0) + 1

        # Success factors
        for sf in f.get("primary_success_factors", []):
            success_factors[sf] = success_factors.get(sf, 0) + 1

        # Tools
        for tool in f.get("tools_effective", []):
            tools_effective[tool] = tools_effective.get(tool, 0) + 1
        for tp in f.get("tools_problematic", []):
            tool_name = tp.get("tool", tp) if isinstance(tp, dict) else str(tp)
            tools_problematic[tool_name] = tools_problematic.get(tool_name, 0) + 1

        # Repeated instructions
        for instr in f.get("repeated_instructions", []):
            if instr:
                repeated_instructions_all.append(instr)

    # Aggregate repeated instructions by frequency
    instruction_counts: dict[str, int] = {}
    for instr in repeated_instructions_all:
        # Normalize
        key = instr.strip().lower()
        instruction_counts[key] = instruction_counts.get(key, 0) + 1

    repeated_instructions_summary = [
        {"instruction": instr, "frequency": count}
        for instr, count in sorted(instruction_counts.items(), key=lambda x: -x[1])
        if count >= 2  # Only surface if repeated
    ][:10]

    n = len(all_facets)
    return {
        "sessions_with_facets": n,
        "goal_categories": sorted(goal_categories.items(), key=lambda x: -x[1]),
        "outcomes": outcomes,
        "satisfaction": satisfaction,
        "helpfulness": helpfulness,
        "session_types": session_types,
        "complexity_distribution": complexities,
        "friction_types": sorted(friction_types.items(), key=lambda x: -x[1]),
        "success_factors": sorted(success_factors.items(), key=lambda x: -x[1]),
        "tools_effective": sorted(tools_effective.items(), key=lambda x: -x[1])[:10],
        "tools_problematic": sorted(tools_problematic.items(), key=lambda x: -x[1])[:10],
        "repeated_instructions": repeated_instructions_summary,
    }
