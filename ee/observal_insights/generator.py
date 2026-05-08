"""Main report generation orchestrator for Agent Insights.

This module coordinates the full insight generation pipeline:
1. Fetch session metadata from ClickHouse (with caching)
2. Enrich session metadata
3. Build transcripts for substantive sessions
4. Extract facets from transcripts (with caching)
5. Compute quantitative metrics
6. Detect regressions against previous period
7. Generate narrative sections via LLM
8. Return structured results for the host app to persist

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

REPORT_VERSION = "2.0"

# Maximum number of sessions to build transcripts for (most recent / most substantive)
MAX_TRANSCRIPT_SESSIONS = 30
# Maximum sessions to include in the LLM data block
MAX_SESSIONS_IN_PROMPT = 75
# Minimum tool calls for a session to be worth extracting facets from
MIN_SUBSTANTIVE_TOOL_CALLS = 3


async def generate_report_content(
    agent_name: str,
    agent_id: str,
    period_start: str,
    period_end: str,
    previous_metrics: dict | None = None,
    db=None,
) -> dict:
    """Generate a complete insight report for an agent over a time period.

    This is the main entry point for the insight generation pipeline.

    Args:
        agent_name: Display name of the agent.
        agent_id: The agent UUID (as string).
        period_start: ISO timestamp for the reporting period start.
        period_end: ISO timestamp for the reporting period end.
        previous_metrics: Metrics dict from the previous report period (for regression detection).
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
            db=db,
            settings=settings,
        )
    finally:
        if owns_session:
            await db.close()


async def _run_pipeline(
    agent_name: str,
    agent_id: str,
    period_start: str,
    period_end: str,
    previous_metrics: dict | None,
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
    )

    # -- Step 1: Fetch session metadata --
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
                }
            },
            "sessions_analyzed": 0,
            "models_used": [],
            "report_version": REPORT_VERSION,
            "regressions": [],
            "facets_summary": {},
        }

    sessions = list(session_metas.values())
    logger.info("insight_sessions_loaded", count=len(sessions))

    # -- Step 2: Enrich session metadata --
    enriched_metas = enrich_all_metas(session_metas)
    enriched_sessions = list(enriched_metas.values())

    # -- Step 3: Compute metrics --
    metrics = await compute_all_metrics(agent_name, period_start, period_end)

    # -- Step 3b: Cross-user pattern detection (deterministic) --
    cross_user_patterns = await compute_cross_user_patterns(enriched_metas)

    # -- Step 4: Build transcripts for substantive sessions --
    substantive_sessions = [(sid, meta) for sid, meta in enriched_metas.items() if meta.get("is_substantive", False)]
    # Sort by duration descending, take top N
    substantive_sessions.sort(key=lambda x: int(x[1].get("duration_seconds", 0)), reverse=True)
    substantive_sessions = substantive_sessions[:MAX_TRANSCRIPT_SESSIONS]

    transcripts: dict[str, str] = {}
    if substantive_sessions:
        transcript_tasks = [
            build_session_transcript(
                session_id=sid,
                start=meta.get("start_time", period_start),
                end=meta.get("end_time", period_end),
            )
            for sid, meta in substantive_sessions
        ]
        transcript_results = await asyncio.gather(*transcript_tasks, return_exceptions=True)
        for (sid, _), result in zip(substantive_sessions, transcript_results):
            if isinstance(result, str) and result:
                transcripts[sid] = result

    logger.info("insight_transcripts_built", count=len(transcripts))

    # -- Step 5: Extract facets from transcripts --
    all_facets: list[dict] = []
    if transcripts:
        facet_tasks = [
            extract_and_cache_facets(
                session_id=sid,
                transcript=transcript,
                meta=enriched_metas.get(sid, {}),
                agent_id=agent_id,
                db=db,
            )
            for sid, transcript in transcripts.items()
        ]
        facet_results = await asyncio.gather(*facet_tasks, return_exceptions=True)
        for result in facet_results:
            if isinstance(result, dict) and result:
                all_facets.append(result)

    facets_summary = aggregate_facets(all_facets)
    logger.info("insight_facets_extracted", count=len(all_facets))

    # -- Step 6: Detect regressions --
    regressions = []
    if previous_metrics:
        regressions = detect_regressions(metrics, previous_metrics)
        logger.info("insight_regressions_detected", count=len(regressions))

    # -- Step 7: Build data block for LLM narrative generation --
    data_block = _build_data_block(
        agent_name=agent_name,
        metrics=metrics,
        session_metas=enriched_metas,
        facet_summary=facets_summary,
        regressions=regressions,
        period_start=period_start,
        period_end=period_end,
        cross_user_patterns=cross_user_patterns,
    )

    # -- Step 8: Generate narrative sections via LLM --
    narrative = await generate_sections(
        data_block=data_block,
        previous_report=previous_metrics,
    )

    # Collect models used
    models_used = list({s.get("model", "") for s in enriched_sessions if s.get("model")})

    logger.info(
        "insight_generation_complete",
        agent_name=agent_name,
        sessions_analyzed=len(sessions),
        facets_extracted=len(all_facets),
        regressions=len(regressions),
    )

    return {
        "metrics": metrics,
        "narrative": narrative,
        "sessions_analyzed": len(sessions),
        "models_used": models_used,
        "report_version": REPORT_VERSION,
        "regressions": regressions,
        "facets_summary": facets_summary,
    }


def _build_data_block(
    agent_name: str,
    metrics: dict,
    session_metas: dict[str, dict],
    facet_summary: dict,
    regressions: list[dict],
    period_start: str,
    period_end: str,
    cross_user_patterns: dict | None = None,
) -> str:
    """Build the DATA_BLOCK string that gets passed to all section prompts."""
    # Anonymize session data for LLM
    meta_list = list(session_metas.values())[:MAX_SESSIONS_IN_PROMPT]
    anonymized = anonymize_sessions(meta_list)

    sections = [
        f"## Agent: {agent_name}",
        f"## Period: {period_start} to {period_end}",
        f"## Sessions Analyzed: {len(session_metas)}",
        "",
        "## Metrics Overview",
        json.dumps(metrics.get("overview", {}), indent=2),
        "",
        "## Token Usage",
        json.dumps(metrics.get("tokens", {}), indent=2),
        "",
        "## Cost Analysis",
        json.dumps(metrics.get("cost", {}), indent=2),
        "",
        "## Error Breakdown",
        json.dumps(metrics.get("errors", {}), indent=2),
        "",
        "## Tool Error Categories",
        json.dumps(metrics.get("tool_errors", {}), indent=2),
        "",
        "## Interruptions & Stop Reasons",
        json.dumps(metrics.get("interruptions", {}), indent=2),
        "",
        "## Duration Stats",
        json.dumps(metrics.get("duration", {}), indent=2),
        "",
        "## Top Tools",
        json.dumps(metrics.get("tools", [])[:15], indent=2),
        "",
        "## Per-Session Data (sample)",
        json.dumps(anonymized[:20], indent=2, default=str),
    ]

    # Add MCP shim metrics if available (Claude Code + Observal shim only)
    mcp = metrics.get("mcp", {})
    if mcp and int(mcp.get("total_mcp_calls", 0)) > 0:
        sections.extend(
            [
                "",
                "## MCP Shim Metrics (precise latency + schema compliance)",
                json.dumps(
                    {
                        "mcp_latency": {
                            "p50": mcp.get("latency_p50_ms", 0),
                            "p95": mcp.get("latency_p95_ms", 0),
                            "p99": mcp.get("latency_p99_ms", 0),
                        },
                        "schema_violations": mcp.get("schema_violations", 0),
                        "schema_violation_rate": mcp.get("schema_violation_rate", 0.0),
                        "tools_available_count": mcp.get("tools_available_count", 0),
                        "slowest_tools": mcp.get("slowest_tools", []),
                        "error_tools": mcp.get("error_tools", []),
                    },
                    indent=2,
                ),
            ]
        )

    # Add facet summary if available
    if facet_summary:
        sections.extend(
            [
                "",
                "## Qualitative Facet Summary (from LLM analysis of individual sessions)",
                json.dumps(facet_summary, indent=2),
            ]
        )

    # Add cross-user patterns if available
    if cross_user_patterns:
        sections.extend(
            [
                "",
                "## Cross-User Patterns",
                json.dumps(cross_user_patterns, indent=2),
            ]
        )

    # Add regression flags if available
    if regressions:
        sections.extend(
            [
                "",
                "## Regression Flags (vs previous period)",
                json.dumps(regressions, indent=2),
            ]
        )

    return "\n".join(sections)
