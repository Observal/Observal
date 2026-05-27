# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: LicenseRef-Observal-Enterprise

"""Insight report generation pipeline.

Ground-up V5 rewrite modeled after pi /insights.

Pipeline:
1. Extract deterministic session metadata from raw JSONL in ClickHouse
2. Build transcripts for top sessions (for facet extraction)
3. Extract facets via Haiku (goal, outcome, satisfaction, friction, instructions)
4. Aggregate metas + facets into a focused data block
5. Run 7 parallel section prompts + 1 synthesis via Opus/Sonnet
6. Return structured report
"""

from __future__ import annotations

import asyncio
import json

import structlog

from ._deps import get_db_session
from .facets import aggregate_facets, extract_and_cache_facets
from .sections import generate_sections
from .session_meta_extractor import aggregate_metas, extract_all_session_metas
from .transcript import build_session_transcript

logger = structlog.get_logger(__name__)

REPORT_VERSION = "5.0"

# How many sessions get full transcript + facet extraction
MAX_FACET_SESSIONS = 50


async def generate_report_content(
    agent_name: str,
    agent_id: str | None = None,
    period_start: str = "",
    period_end: str = "",
    previous_metrics: dict | None = None,
    agent_config: dict | None = None,
    registry_catalog: dict | None = None,
    db=None,
) -> dict:
    """Generate a complete insight report for an agent.

    This is the main entry point. The host app (observal-server) handles
    DB persistence of the result.
    """
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
            registry_catalog=registry_catalog,
            db=db,
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
    registry_catalog: dict | None,
    db=None,
) -> dict:
    """Core pipeline execution."""

    logger.info(
        "insight_pipeline_started",
        agent=agent_name,
        agent_id=agent_id,
        period=f"{period_start} to {period_end}",
    )

    # ── Step 1: Deterministic metadata extraction from raw JSONL ──────────
    # This reads actual session content from ClickHouse and computes:
    # lines added/removed, git commits, languages, tool errors, response
    # times, subagent usage, cost, etc.
    session_metas = await extract_all_session_metas(
        agent_id=agent_id or "",
        period_start=period_start,
        period_end=period_end,
        agent_name=agent_name,
    )

    if not session_metas:
        logger.warning("insight_no_sessions", agent_id=agent_id)
        return _empty_report()

    logger.info("insight_metas_extracted", count=len(session_metas))

    # Aggregate deterministic stats
    agg = aggregate_metas(session_metas)

    # ── Step 2: Build transcripts for top sessions ────────────────────────
    # Sort by substantiveness (duration * tool_calls), take top N
    ranked = sorted(
        session_metas,
        key=lambda m: m.get("duration_seconds", 0) * sum(m.get("tool_counts", {}).values()),
        reverse=True,
    )
    # Filter trivial sessions (< 2 user messages or < 60 seconds)
    substantive = [m for m in ranked if m.get("user_message_count", 0) >= 2 and m.get("duration_seconds", 0) >= 60]
    top_sessions = substantive[:MAX_FACET_SESSIONS]

    transcripts: dict[str, str] = {}
    if top_sessions:
        transcript_tasks = [build_session_transcript(m["session_id"]) for m in top_sessions]
        results = await asyncio.gather(*transcript_tasks, return_exceptions=True)
        for meta, result in zip(top_sessions, results, strict=False):
            if isinstance(result, str) and result.strip():
                transcripts[meta["session_id"]] = result

    logger.info("insight_transcripts_built", count=len(transcripts))

    # ── Step 3: Extract facets (concurrency-limited Haiku calls) ──────────
    import services.dynamic_settings as ds

    max_concurrent = int(await ds.get("insights.facet_concurrency") or 5)

    all_facets: list[dict] = []
    if transcripts:
        all_facets = await _extract_facets_batch(
            transcripts=transcripts,
            session_metas={m["session_id"]: m for m in session_metas},
            agent_id=agent_id or "",
            db=db,
            max_concurrent=max_concurrent,
        )

    logger.info("insight_facets_extracted", count=len(all_facets))

    # ── Step 4: Build the data block (pi-style focused format) ────────────
    facets_summary = aggregate_facets(all_facets)
    data_block = _build_data_block(
        agent_name=agent_name,
        agg=agg,
        facets_summary=facets_summary,
        all_facets=all_facets,
        period_start=period_start,
        period_end=period_end,
        agent_config=agent_config,
    )

    # ── Step 5: Generate narrative sections (7 parallel + 1 synthesis) ────
    narrative = await generate_sections(
        data_block=data_block,
        previous_report=previous_metrics,
        registry_catalog=registry_catalog,
    )

    logger.info(
        "insight_pipeline_complete",
        sessions=len(session_metas),
        facets=len(all_facets),
    )

    # ── Build final report structure ──────────────────────────────────────
    # metrics.rich is what the frontend reads for stat cards
    metrics = {
        "rich": {
            "total_sessions": agg.get("total_sessions", 0),
            "total_messages": agg.get("total_messages", 0),
            "active_hours": round(agg.get("total_duration_hours", 0), 1),
            "days_active": agg.get("days_active", 0),
            "lines_added": agg.get("total_lines_added", 0),
            "lines_removed": agg.get("total_lines_removed", 0),
            "files_modified": agg.get("total_files_modified", 0),
            "git_commits": agg.get("git_commits", 0),
            "git_pushes": agg.get("git_pushes", 0),
            "tool_errors": agg.get("total_tool_errors", 0),
            "interruptions": agg.get("total_interruptions", 0),
            "subagent_sessions": agg.get("sessions_using_subagent", 0),
            "mcp_sessions": agg.get("sessions_using_mcp", 0),
            "total_cost_usd": round(agg.get("total_cost", 0), 2),
            "total_input_tokens": agg.get("total_input_tokens", 0),
            "total_output_tokens": agg.get("total_output_tokens", 0),
            "total_cache_read_tokens": agg.get("total_cache_read_tokens", 0),
            "total_cache_write_tokens": agg.get("total_cache_write_tokens", 0),
            "top_tools": agg.get("top_tools", [])[:15],
            "top_languages": agg.get("top_languages", [])[:10],
            "tool_error_categories": agg.get("tool_error_categories", {}),
            "projects": agg.get("projects", {}),
        },
        "overview": {
            "total_sessions": agg.get("total_sessions", 0),
            "unique_users": 1,  # single-user context for now
        },
    }

    return {
        "metrics": metrics,
        "narrative": narrative,
        "sessions_analyzed": len(session_metas),
        "models_used": [],
        "report_version": REPORT_VERSION,
        "regressions": [],
        "facets_summary": facets_summary,
        "cross_user_patterns": {},
    }


async def _extract_facets_batch(
    transcripts: dict[str, str],
    session_metas: dict[str, dict],
    agent_id: str,
    db,
    max_concurrent: int = 5,
) -> list[dict]:
    """Extract facets with concurrency limit."""
    semaphore = asyncio.Semaphore(max_concurrent)

    async def _one(sid: str, transcript: str) -> dict:
        async with semaphore:
            return await extract_and_cache_facets(
                session_id=sid,
                transcript=transcript,
                meta=session_metas.get(sid, {}),
                agent_id=agent_id,
                db=db,
            )

    tasks = [_one(sid, t) for sid, t in transcripts.items()]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    for r in results:
        if isinstance(r, Exception):
            logger.warning("facet_task_exception", error=str(r), type=type(r).__name__)

    return [r for r in results if isinstance(r, dict) and r]


def _build_data_block(
    agent_name: str,
    agg: dict,
    facets_summary: dict,
    all_facets: list[dict],
    period_start: str,
    period_end: str,
    agent_config: dict | None = None,
) -> str:
    """Build the DATA_BLOCK for section prompts.

    Modeled after pi's buildSharedDataBlock: a focused JSON summary plus
    SESSION SUMMARIES, FRICTION DETAILS, and USER INSTRUCTIONS as text.
    This is what the LLM actually reads. Keep it tight and information-dense.
    """

    # Top 8 helper
    def top8(rec: dict) -> list[list]:
        return sorted(rec.items(), key=lambda x: -x[1])[:8]

    # Core summary (like pi's buildSharedDataBlock JSON)
    summary = {
        "agent": agent_name,
        "period": f"{period_start} to {period_end}",
        "sessions": agg.get("total_sessions", 0),
        "sessions_with_facets": facets_summary.get("sessions_with_facets", 0),
        "date_range": agg.get("date_range", {}),
        "messages": agg.get("total_messages", 0),
        "hours": round(agg.get("total_duration_hours", 0)),
        "days_active": agg.get("days_active", 0),
        "commits": agg.get("git_commits", 0),
        "pushes": agg.get("git_pushes", 0),
        "cost_usd": round(agg.get("total_cost", 0), 2),
        "lines_added": agg.get("total_lines_added", 0),
        "lines_removed": agg.get("total_lines_removed", 0),
        "files_modified": agg.get("total_files_modified", 0),
        "tool_errors": agg.get("total_tool_errors", 0),
        "interruptions": agg.get("total_interruptions", 0),
        "subagent_sessions": agg.get("sessions_using_subagent", 0),
        "mcp_sessions": agg.get("sessions_using_mcp", 0),
        "top_tools": agg.get("top_tools", [])[:10],
        "top_languages": agg.get("top_languages", [])[:10],
        "tool_error_categories": agg.get("tool_error_categories", {}),
        "projects": agg.get("projects", {}),
        # From facets aggregation
        "top_goals": facets_summary.get("goal_categories", [])[:10],
        "outcomes": facets_summary.get("outcomes", {}),
        "satisfaction": facets_summary.get("satisfaction", {}),
        "helpfulness": facets_summary.get("helpfulness", {}),
        "friction": facets_summary.get("friction_types", [])[:10],
        "success": facets_summary.get("success_factors", [])[:10],
        "session_types": facets_summary.get("session_types", {}),
        "complexity": facets_summary.get("complexity_distribution", {}),
    }

    # Multi-session detection
    if agg.get("multi_clauding"):
        summary["multi_clauding"] = agg["multi_clauding"]

    sections = [json.dumps(summary, indent=2)]

    # Agent configuration (for component-aware suggestions)
    if agent_config:
        sections.append(f"\n## Agent Configuration\n{json.dumps(agent_config, indent=2)}")

    # SESSION SUMMARIES (the key differentiator from old evals approach)
    if all_facets:
        summaries = []
        for f in all_facets[-50:]:
            if not f:
                continue
            brief = f.get("brief_summary", "")
            outcome = f.get("outcome", "unclear")
            helpfulness = f.get("agent_helpfulness", "unknown")
            if brief:
                summaries.append(f"- {brief} ({outcome}, {helpfulness})")

        if summaries:
            sections.append("\nSESSION SUMMARIES:\n" + "\n".join(summaries))

        # FRICTION DETAILS (specific examples the LLM can cite)
        friction_details = []
        for f in all_facets:
            if not f:
                continue
            for fp in f.get("friction_points", []):
                desc = fp.get("description", "")
                ftype = fp.get("type", "")
                if desc:
                    friction_details.append(f"- [{ftype}] {desc}")

        if friction_details:
            sections.append("\nFRICTION DETAILS:\n" + "\n".join(friction_details[:30]))

        # USER INSTRUCTIONS TO ASSISTANT (repeated patterns)
        user_instructions = []
        for f in all_facets:
            if not f:
                continue
            for instr in f.get("repeated_instructions", []):
                if instr:
                    user_instructions.append(f"- {instr}")

        if user_instructions:
            sections.append("\nUSER INSTRUCTIONS TO ASSISTANT:\n" + "\n".join(user_instructions[:20]))

    # Repeated instructions summary (aggregated)
    repeated = facets_summary.get("repeated_instructions", [])
    if repeated:
        sections.append(
            "\nREPEATED INSTRUCTIONS (by frequency):\n"
            + "\n".join(f'- "{r["instruction"]}" (frequency: {r["frequency"]})' for r in repeated[:10])
        )

    return "\n".join(sections)


def _empty_report() -> dict:
    """Return an empty report structure when no sessions exist."""
    return {
        "metrics": {},
        "narrative": {
            "at_a_glance": {
                "health": "unknown",
                "whats_working": "No session data available for this period.",
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
