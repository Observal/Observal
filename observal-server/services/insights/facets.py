"""Per-session LLM facet extraction for qualitative insights."""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime

import structlog
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from models.insight_session_facets import InsightSessionFacets
from services.eval.eval_service import call_eval_model
from services.insights.transcript import build_session_transcript

logger = structlog.get_logger(__name__)


def _get_facet_model() -> str | None:
    """Get the model for facet extraction (Haiku for cost efficiency)."""
    return getattr(settings, "INSIGHT_MODEL_FACETS", "") or None

FACET_PROMPT = """Analyze this AI coding agent session transcript and extract structured facets.

## Transcript
{transcript}

## Instructions
Extract the following structured data about this session:

Respond with JSON matching this exact structure:
{{
  "underlying_goal": "what the user was trying to accomplish (1 sentence)",
  "goal_category": "implement_feature|fix_bug|refactor|investigate|configure|test|documentation|exploration|quick_question|other",
  "outcome": "fully_achieved|mostly_achieved|partially_achieved|not_achieved|unclear",
  "satisfaction_signal": "positive|neutral|negative|unclear",
  "friction_types": ["edit_failed", "command_failed", ...],
  "friction_detail": "one sentence describing main friction or empty string",
  "session_type": "single_task|multi_task|iterative_refinement|exploration|quick_question",
  "brief_summary": "one sentence summary of what happened"
}}

If the transcript is too short to determine something, use "unclear" or empty values."""


async def load_cached_facets(
    db: AsyncSession, agent_id: uuid.UUID, session_ids: list[str]
) -> dict[str, dict]:
    """Load cached facets from PostgreSQL."""
    if not session_ids:
        return {}

    stmt = select(InsightSessionFacets).where(
        InsightSessionFacets.agent_id == agent_id,
        InsightSessionFacets.session_id.in_(session_ids),
    )
    result = await db.execute(stmt)
    rows = result.scalars().all()
    return {row.session_id: row.facets for row in rows}


async def store_facets(
    db: AsyncSession, agent_id: uuid.UUID, facets: dict[str, dict], model_used: str
) -> None:
    """Store extracted facets in PostgreSQL (upsert)."""
    if not facets:
        return

    now = datetime.now(UTC)
    for session_id, facet_data in facets.items():
        stmt = pg_insert(InsightSessionFacets).values(
            id=uuid.uuid4(),
            agent_id=agent_id,
            session_id=session_id,
            extracted_at=now,
            model_used=model_used,
            facets=facet_data,
        ).on_conflict_do_update(
            constraint="uq_session_facets_agent_session",
            set_={"facets": facet_data, "extracted_at": now, "model_used": model_used},
        )
        await db.execute(stmt)
    await db.flush()


async def _extract_single_facet(
    session_id: str, start: str, end: str, semaphore: asyncio.Semaphore
) -> tuple[str, dict | None]:
    """Extract facets for a single session with concurrency control."""
    async with semaphore:
        transcript = await build_session_transcript(session_id, start, end)
        if len(transcript) < 100:
            return session_id, None

        prompt = FACET_PROMPT.format(transcript=transcript)
        facet_model = _get_facet_model()
        try:
            result = await call_eval_model(prompt, model_override=facet_model, max_tokens=4096)
            if result and isinstance(result, dict):
                return session_id, result
            return session_id, None
        except Exception as e:
            logger.warning("facet_extraction_failed", session_id=session_id, error=str(e))
            return session_id, None


async def extract_facets_batch(
    db: AsyncSession,
    agent_id: uuid.UUID,
    session_metas: dict[str, dict],
    start: str,
    end: str,
    max_calls: int | None = None,
    concurrency: int | None = None,
) -> dict[str, dict]:
    """Extract facets for sessions that don't have cached facets.

    Only processes sessions with >= 3 tool calls AND >= 60s duration.
    Returns all facets (cached + newly extracted).
    """
    if max_calls is None:
        max_calls = getattr(settings, "INSIGHT_FACET_MAX_CALLS", 100)
    if concurrency is None:
        concurrency = getattr(settings, "INSIGHT_FACET_CONCURRENCY", 25)

    # Filter to substantive sessions
    substantive_ids = [
        sid for sid, meta in session_metas.items()
        if int(meta.get("tool_call_count", 0)) >= 3
        and int(meta.get("duration_seconds", 0)) >= 60
    ]

    if not substantive_ids:
        return {}

    # Load cached
    cached = await load_cached_facets(db, agent_id, substantive_ids)
    uncached_ids = [sid for sid in substantive_ids if sid not in cached]

    if not uncached_ids:
        return cached

    # Cap at max_calls
    to_process = uncached_ids[:max_calls]
    semaphore = asyncio.Semaphore(concurrency)

    # Extract in parallel with concurrency limit
    tasks = [_extract_single_facet(sid, start, end, semaphore) for sid in to_process]
    results = await asyncio.gather(*tasks)

    # Collect successful extractions
    new_facets: dict[str, dict] = {}
    for session_id, facet in results:
        if facet:
            new_facets[session_id] = facet

    # Store new facets
    if new_facets:
        model_used = getattr(settings, "EVAL_MODEL_NAME", "unknown")
        await store_facets(db, agent_id, new_facets, model_used)

    # Return all (cached + new)
    cached.update(new_facets)
    return cached


def aggregate_facets(facets: dict[str, dict]) -> dict:
    """Aggregate individual session facets into summary distributions."""
    if not facets:
        return {}

    outcome_dist: dict[str, int] = {}
    goal_categories: dict[str, int] = {}
    friction_types: dict[str, int] = {}
    session_types: dict[str, int] = {}
    satisfaction: dict[str, int] = {}

    for facet in facets.values():
        # Outcome
        outcome = facet.get("outcome", "unclear")
        outcome_dist[outcome] = outcome_dist.get(outcome, 0) + 1

        # Goal category
        cat = facet.get("goal_category", "other")
        goal_categories[cat] = goal_categories.get(cat, 0) + 1

        # Friction types
        for ft in facet.get("friction_types", []):
            friction_types[ft] = friction_types.get(ft, 0) + 1

        # Session type
        st = facet.get("session_type", "other")
        session_types[st] = session_types.get(st, 0) + 1

        # Satisfaction
        sat = facet.get("satisfaction_signal", "unclear")
        satisfaction[sat] = satisfaction.get(sat, 0) + 1

    return {
        "total_sessions_with_facets": len(facets),
        "outcome_distribution": outcome_dist,
        "goal_categories": goal_categories,
        "friction_types": friction_types,
        "session_type_distribution": session_types,
        "satisfaction": satisfaction,
    }
