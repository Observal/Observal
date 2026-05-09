"""Main report generation orchestrator for Agent Insights (V3).

This module coordinates the full insight generation pipeline:
1. Fetch session metadata (from session_events via agent_id, fallback to otel_logs)
2. Enrich session metadata (add completeness, is_substantive)
3. Filter & Rank Sessions (remove non-substantive, rank by duration x tool_call_count)
4. Compute deterministic metrics (parallel ClickHouse queries via compute_all_metrics)
4b. Cross-user patterns (deterministic, includes multi-session and subagent analysis)
5. Build transcripts (top 50 sessions, from session_events.raw_line)
6. Extract facets (with staleness-aware caching, up to 50 concurrent)
7. Aggregate & enrich (aggregate facets, detect regressions)
8. Build data block (for LLM narrative generation)
9. Generate narrative sections (8 parallel + 1 synthesis)

The host application (observal-server) is responsible for:
- Loading the report/agent from PostgreSQL
- Calling generate_report_content() with the necessary parameters
- Persisting the results back to the database
"""

from __future__ import annotations

import asyncio
import json

import structlog

from ._deps import get_db_session, get_settings
from .anonymize import anonymize_sessions
from .cross_user import compute_cross_user_patterns
from .enrichment import enrich_all_metas
from .facets import aggregate_facets, extract_and_cache_facets
from .metrics import compute_all_metrics
from .regression import detect_regressions
from .sections import generate_sections
from .session_cache import get_session_metas
from .transcript import build_session_transcript

logger = structlog.get_logger(__name__)

REPORT_VERSION = "3.0"

# Maximum number of sessions to build transcripts for (most substantive)
MAX_TRANSCRIPT_SESSIONS = 50
# Maximum sessions to include in the LLM data block
MAX_SESSIONS_IN_PROMPT = 75
# Minimum tool calls for a session to be considered substantive
MIN_SUBSTANTIVE_TOOL_CALLS = 3


async def generate_report_content(
    agent_name: str,
    agent_id: str | None = None,
    period_start: str = "",
    period_end: str = "",
    previous_metrics: dict | None = None,
    agent_config: dict | None = None,
    db=None,
) -> dict:
    """Generate a complete insight report for an agent over a time period.

    This is the main entry point for the insight generation pipeline.

    Args:
        agent_name: Display name of the agent (used for otel_logs fallback).
        agent_id: The agent UUID (as string). Primary lookup key for session_events.
        period_start: ISO timestamp for the reporting period start.
        period_end: ISO timestamp for the reporting period end.
        previous_metrics: Metrics dict from the previous report period (for regression detection).
        agent_config: Agent configuration dict (system prompt, MCPs, skills, model) for
            component-aware suggestions. Loaded from the latest approved AgentVersion.
        db: Optional AsyncSession for caching. If None, a new session is created from _deps.

    Returns:
        Dict with keys:
            - metrics: quantitative metrics dict
            - narrative: structured narrative sections dict
            - sessions_analyzed: number of sessions processed
            - models_used: list of model names used in generation
            - report_version: format version string
            - regressions: list of detected regressions
            - facets_summary: aggregated facets dict
            - cross_user_patterns: cross-user pattern dict (V3)
    """
    settings = get_settings()

    # Acquire a DB session if not provided
    owns_session = False
    if db is None:
        session_factory = get_db_session()
        db = session_factory()
        owns_session = True

    try:
        return await _run_pipeline(
            agent_name=agent_name,
            agent_id=agent_id,
            period_start=period_start,
            period_end=period_end,
            previous_metrics=previous_metrics,
            agent_config=agent_config,
            db=db,
            settings=settings,
        )
    finally:
        if owns_session:
            await db.close()


async def _run_pipeline(
    agent_name: str,
    agent_id: str | None,
    period_start: str,
    period_end: str,
    previous_metrics: dict | None,
    agent_config: dict | None,
    db,
    settings,
) -> dict:
    """Internal pipeline execution."""

    logger.info(
        "insight_generation_started",
        agent_name=agent_name,
        agent_id=agent_id,
        period_start=period_start,
        period_end=period_end,
        report_version=REPORT_VERSION,
    )

    # ── Step 1: Fetch session metadata ──
    # Uses session_events via agent_id as primary source, falls back to otel_logs
    session_metas = await get_session_metas(
        agent_id=agent_id,
        agent_name=agent_name,
        period_start=period_start,
        period_end=period_end,
        db=db,
        use_cache=True,
    )

    if not session_metas:
        logger.warning("insight_no_sessions", agent_id=agent_id)
        return {
            "metrics": {},
            "narrative": {
                "at_a_glance": {
                    "health": "unknown",
                    "whats_working": "No session data available.",
                    "whats_hindering": "N/A",
                    "quick_win": "N/A",
                },
            },
            "sessions_analyzed": 0,
            "models_used": [],
            "report_version": REPORT_VERSION,
            "regressions": [],
            "facets_summary": {},
            "cross_user_patterns": {},
        }

    sessions = list(session_metas.values())
    logger.info("insight_sessions_loaded", count=len(sessions))

    # ── Step 2: Enrich session metadata (add completeness, is_substantive) ──
    enriched_metas = enrich_all_metas(session_metas)
    enriched_sessions = list(enriched_metas.values())

    # ── Step 3: Filter & Rank Sessions ──
    # Remove non-substantive sessions and rank by duration x tool_call_count
    substantive_sessions = [(sid, meta) for sid, meta in enriched_metas.items() if meta.get("is_substantive", False)]
    # Sort by substantiveness score: duration_seconds * tool_call_count (descending)
    substantive_sessions.sort(
        key=lambda x: int(x[1].get("duration_seconds", 0)) * int(x[1].get("tool_call_count", 0)),
        reverse=True,
    )

    # ── Step 4: Compute deterministic metrics (parallel ClickHouse queries) ──
    metrics = await compute_all_metrics(agent_name, period_start, period_end, agent_id=agent_id)

    # ── Step 4b: Cross-user patterns (deterministic, multi-session + subagent) ──
    cross_user_patterns = await compute_cross_user_patterns(enriched_metas)

    logger.info(
        "insight_metrics_computed",
        metric_keys=list(metrics.keys()) if metrics else [],
    )

    # ── Step 5: Build transcripts (top 50 sessions, from session_events.raw_line) ──
    top_sessions = substantive_sessions[:MAX_TRANSCRIPT_SESSIONS]

    transcripts: dict[str, str] = {}
    if top_sessions:
        transcript_tasks = [
            build_session_transcript(
                session_id=sid,
                start=meta.get("start_time", period_start),
                end=meta.get("end_time", period_end),
            )
            for sid, meta in top_sessions
        ]
        transcript_results = await asyncio.gather(*transcript_tasks, return_exceptions=True)
        for (sid, _), result in zip(top_sessions, transcript_results):
            if isinstance(result, str) and result:
                transcripts[sid] = result

    logger.info("insight_transcripts_built", count=len(transcripts))

    # ── Step 6: Extract facets (staleness-aware caching, concurrency-limited) ──
    max_concurrent = getattr(settings, "INSIGHT_FACET_CONCURRENCY", 50)
    all_facets: list[dict] = []
    if transcripts:
        all_facets = await _extract_facets_with_concurrency(
            transcripts=transcripts,
            enriched_metas=enriched_metas,
            agent_id=agent_id or "",
            db=db,
            max_concurrent=max_concurrent,
        )

    logger.info("insight_facets_extracted", count=len(all_facets))

    # ── Step 7: Aggregate & enrich (aggregate facets, detect regressions) ──
    facets_summary = aggregate_facets(all_facets)

    regressions = []
    if previous_metrics:
        regressions = detect_regressions(metrics, previous_metrics)
        logger.info("insight_regressions_detected", count=len(regressions))

    # ── Step 8: Build data block for LLM narrative generation ──
    data_block = _build_data_block(
        agent_name=agent_name,
        metrics=metrics,
        session_metas=enriched_metas,
        facet_summary=facets_summary,
        regressions=regressions,
        period_start=period_start,
        period_end=period_end,
        cross_user_patterns=cross_user_patterns,
        agent_config=agent_config,
    )

    # ── Step 9: Generate narrative sections (8 parallel + 1 synthesis) ──
    narrative = await generate_sections(
        data_block=data_block,
        previous_report=previous_metrics,
    )

    # Collect models used across sessions
    models_used = list({s.get("model", "") for s in enriched_sessions if s.get("model")})

    logger.info(
        "insight_generation_complete",
        agent_name=agent_name,
        sessions_analyzed=len(sessions),
        facets_extracted=len(all_facets),
        regressions=len(regressions),
        report_version=REPORT_VERSION,
    )

    return {
        "metrics": metrics,
        "narrative": narrative,
        "sessions_analyzed": len(sessions),
        "models_used": models_used,
        "report_version": REPORT_VERSION,
        "regressions": regressions,
        "facets_summary": facets_summary,
        "cross_user_patterns": cross_user_patterns,
    }


async def _extract_facets_with_concurrency(
    transcripts: dict[str, str],
    enriched_metas: dict[str, dict],
    agent_id: str,
    db,
    max_concurrent: int = 50,
) -> list[dict]:
    """Extract facets with concurrency limit."""
    semaphore = asyncio.Semaphore(max_concurrent)

    async def _extract_one(sid: str, transcript: str) -> dict:
        async with semaphore:
            return await extract_and_cache_facets(
                session_id=sid,
                transcript=transcript,
                meta=enriched_metas.get(sid, {}),
                agent_id=agent_id,
                db=db,
            )

    tasks = [_extract_one(sid, t) for sid, t in transcripts.items()]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    return [r for r in results if isinstance(r, dict) and r]


def _build_data_block(
    agent_name: str,
    metrics: dict,
    session_metas: dict[str, dict],
    facet_summary: dict,
    regressions: list[dict],
    period_start: str,
    period_end: str,
    cross_user_patterns: dict | None = None,
    agent_config: dict | None = None,
) -> str:
    """Build the DATA_BLOCK string for all section prompts."""
    meta_list = list(session_metas.values())[:MAX_SESSIONS_IN_PROMPT]
    anonymized = anonymize_sessions(meta_list)

    sections = [
        f"## Agent: {agent_name}",
        f"## Period: {period_start} to {period_end}",
        f"## Sessions Analyzed: {len(session_metas)}",
        "",
    ]

    # Agent configuration (for component-aware suggestions)
    if agent_config:
        sections.extend(
            [
                "## Agent Configuration",
                json.dumps(agent_config, indent=2),
                "",
            ]
        )

    sections.extend(
        [
            "## Metrics Overview",
            json.dumps(metrics.get("overview", {}), indent=2),
            "",
            "## Token Usage",
            json.dumps(metrics.get("tokens", {}), indent=2),
            "",
        ]
    )

    # Credits (Kiro) if available
    credits = metrics.get("credits", {})
    if credits and int(credits.get("total_credits", 0)) > 0:
        sections.extend(
            [
                "## Credit Usage (Kiro)",
                json.dumps(credits, indent=2),
                "",
            ]
        )

    sections.extend(
        [
            "## Cost Analysis",
            json.dumps(metrics.get("cost", {}), indent=2),
            "",
            "## Error Breakdown",
            json.dumps(metrics.get("errors", {}), indent=2),
            "",
            "## Tool Error Categories",
            json.dumps(metrics.get("tool_errors", {}), indent=2),
            "",
            "## Interruptions",
            json.dumps(metrics.get("interruptions", {}), indent=2),
            "",
            "## Duration Stats",
            json.dumps(metrics.get("duration", {}), indent=2),
            "",
            "## Top Tools",
            json.dumps(metrics.get("tools", [])[:15], indent=2),
            "",
        ]
    )

    # V3 additions: git stats
    git = metrics.get("git", {})
    if git and (int(git.get("commits", 0)) > 0 or int(git.get("pushes", 0)) > 0):
        sections.extend(
            [
                "## Git Stats",
                json.dumps(git, indent=2),
                "",
            ]
        )

    # V3 additions: languages
    languages = metrics.get("languages", {})
    if languages:
        sections.extend(
            [
                "## Languages",
                json.dumps(languages, indent=2),
                "",
            ]
        )

    # V3 additions: response times
    response_times = metrics.get("response_times", {})
    if response_times:
        sections.extend(
            [
                "## Response Times",
                json.dumps(response_times, indent=2),
                "",
            ]
        )

    # V3 additions: time of day distribution
    time_of_day = metrics.get("time_of_day", {})
    if time_of_day:
        sections.extend(
            [
                "## Time of Day Distribution",
                json.dumps(time_of_day, indent=2),
                "",
            ]
        )

    # V3 additions: multi-session detection
    multi_session = metrics.get("multi_session", {})
    if multi_session and multi_session.get("detected"):
        sections.extend(
            [
                "## Multi-Session Detection",
                json.dumps(multi_session, indent=2),
                "",
            ]
        )

    # V3 additions: subagent stats
    subagents = metrics.get("subagents", {})
    if subagents and int(subagents.get("total_subagent_sessions", 0)) > 0:
        sections.extend(
            [
                "## Subagent Stats",
                json.dumps(subagents, indent=2),
                "",
            ]
        )

    # MCP shim metrics
    mcp = metrics.get("mcp", {})
    if mcp and int(mcp.get("total_mcp_calls", 0)) > 0:
        sections.extend(
            [
                "## MCP Shim Metrics",
                json.dumps(mcp, indent=2),
                "",
            ]
        )

    # Per-session sample
    sections.extend(
        [
            "## Per-Session Data (sample)",
            json.dumps(anonymized[:20], indent=2, default=str),
        ]
    )

    # Facet summary
    if facet_summary:
        sections.extend(
            [
                "",
                "## Qualitative Facet Summary",
                json.dumps(facet_summary, indent=2),
            ]
        )

    # Cross-user patterns
    if cross_user_patterns:
        sections.extend(
            [
                "",
                "## Cross-User Patterns",
                json.dumps(cross_user_patterns, indent=2),
            ]
        )

    # Regressions
    if regressions:
        sections.extend(
            [
                "",
                "## Regression Flags (vs previous period)",
                json.dumps(regressions, indent=2),
            ]
        )

    return "\n".join(sections)
