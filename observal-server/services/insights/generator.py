"""Insight report generation orchestrator (V2).

Pipeline:
1. Load report + agent → set status=running
2. Compute deterministic metrics (ClickHouse)
2a. [dedup] When per-session raw events are available, call dedupe_session_events()
    to merge hook+OTLP duplicates before computing metadata aggregates.
3. Get per-session metadata (cached or computed)
4. Enrich session metadata (completeness scoring)
5. Extract qualitative facets via LLM (cached, with caps)
6. Compute cost metrics from session data
7. Build anonymized DATA_BLOCK
8. Detect regressions (if previous report exists)
9. Run 8+1 parallel section prompts
10. Store aggregated_data, set status=completed
"""

import json
from datetime import UTC, datetime

import structlog
from sqlalchemy import select

from config import settings
from database import async_session
from models.agent import Agent
from models.insight_report import InsightReport, InsightReportStatus
from services.insights.anonymize import anonymize_sessions
from services.insights.cross_user import compute_cross_user_patterns
from services.insights.dedup import (
    dedupe_session_events,  # noqa: F401 — per-session event dedup when raw events are available
)
from services.insights.enrichment import enrich_all_metas
from services.insights.facets import aggregate_facets, extract_facets_batch
from services.insights.metrics import compute_all_metrics
from services.insights.regression import detect_regressions
from services.insights.sections import generate_sections
from services.insights.session_cache import get_or_compute_metas

logger = structlog.get_logger(__name__)

# Limits
MAX_SESSIONS_IN_PROMPT = 75
MAX_FRICTION_IN_PROMPT = 30


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


async def generate_report(report_id: str) -> None:
    """Generate an insight report: metrics → cache → facets → sections.

    Updates the InsightReport row in Postgres as it progresses.
    """
    async with async_session() as db:
        stmt = select(InsightReport).where(InsightReport.id == report_id)
        result = await db.execute(stmt)
        report = result.scalar_one_or_none()
        if not report:
            logger.error("insight_report_not_found", report_id=report_id)
            return

        # Mark as running
        report.status = InsightReportStatus.running
        report.started_at = datetime.now(UTC)
        await db.commit()

        try:
            # Load agent
            agent_stmt = select(Agent).where(Agent.id == report.agent_id)
            agent_result = await db.execute(agent_stmt)
            agent = agent_result.scalar_one_or_none()
            agent_name = agent.name if agent else "Unknown Agent"

            start_str = report.period_start.strftime("%Y-%m-%d %H:%M:%S")
            end_str = report.period_end.strftime("%Y-%m-%d %H:%M:%S")

            # ── Step 1: Compute deterministic metrics ──
            metrics = await compute_all_metrics(agent_name, start_str, end_str)
            report.metrics = metrics

            session_count = int(metrics.get("overview", {}).get("total_sessions", 0))
            report.sessions_analyzed = session_count
            await db.commit()

            if session_count == 0:
                report.status = InsightReportStatus.completed
                report.completed_at = datetime.now(UTC)
                report.narrative = {"at_a_glance": "No sessions found in this period."}
                report.report_version = 2
                await db.commit()
                return

            # ── Step 2: Get per-session metadata (cached) ──
            session_ids = [s["session_id"] for s in metrics.get("sessions", []) if s.get("session_id")]
            session_metas = await get_or_compute_metas(db, report.agent_id, session_ids, start_str, end_str)

            # ── Step 3: Enrich metadata ──
            session_metas = enrich_all_metas(session_metas)

            # ── Step 3b: Cross-user pattern detection (deterministic) ──
            cross_user_patterns = await compute_cross_user_patterns(session_metas)

            # ── Step 4: Extract facets (LLM, with caching + caps) ──
            facets: dict[str, dict] = {}
            facet_summary: dict = {}
            eval_model = getattr(settings, "EVAL_MODEL_NAME", "") or ""
            if eval_model:
                try:
                    facets = await extract_facets_batch(db, report.agent_id, session_metas, start_str, end_str)
                    facet_summary = aggregate_facets(facets)
                except Exception as e:
                    logger.warning("facet_extraction_skipped", error=str(e))

            # ── Step 5: Load previous report for regression detection ──
            previous_metrics: dict | None = None
            regressions: list[dict] = []
            if report.previous_report_id:
                prev_stmt = select(InsightReport).where(InsightReport.id == report.previous_report_id)
                prev_result = await db.execute(prev_stmt)
                prev_report = prev_result.scalar_one_or_none()
                if prev_report and prev_report.aggregated_data:
                    previous_metrics = prev_report.aggregated_data
                    regressions = detect_regressions(metrics, previous_metrics)

            # ── Step 6: Build DATA_BLOCK and run sections ──
            data_block = _build_data_block(
                agent_name=agent_name,
                metrics=metrics,
                session_metas=session_metas,
                facet_summary=facet_summary,
                regressions=regressions,
                period_start=start_str,
                period_end=end_str,
                cross_user_patterns=cross_user_patterns,
            )

            # Generate narrative (V2: 8+1 parallel sections OR V1 fallback)
            narrative: dict | None = None
            if eval_model:
                try:
                    narrative = await generate_sections(data_block, previous_metrics)
                    # Add regression flags to narrative for frontend
                    if regressions:
                        narrative["regressions"] = regressions
                except Exception as e:
                    logger.error("sections_generation_failed", error=str(e))
                    # Fall back to V1 narrative
                    from services.insights.narrative import generate_narrative

                    narrative = await generate_narrative(
                        agent_name=agent_name,
                        metrics=metrics,
                        period_start=start_str,
                        period_end=end_str,
                        session_count=session_count,
                    )

            report.narrative = narrative
            # Record models used (multi-model pipeline)
            section_model = getattr(settings, "INSIGHT_MODEL_SECTIONS", "") or eval_model
            synthesis_model = getattr(settings, "INSIGHT_MODEL_SYNTHESIS", "") or eval_model
            facet_model = getattr(settings, "INSIGHT_MODEL_FACETS", "") or eval_model
            models_used = sorted(set(filter(None, [section_model, synthesis_model, facet_model])))
            report.llm_model_used = ", ".join(models_used) if narrative else None
            report.report_version = 2 if narrative and "user_experience" in (narrative or {}) else 1

            # Store aggregated data for future regression comparison
            report.aggregated_data = metrics

            # ── Complete ──
            report.status = InsightReportStatus.completed
            report.completed_at = datetime.now(UTC)
            await db.commit()

            logger.info(
                "insight_report_completed",
                report_id=report_id,
                sessions=session_count,
                has_narrative=narrative is not None,
                version=report.report_version,
                facets_extracted=len(facets),
                regressions_detected=len(regressions),
            )

        except Exception as e:
            report.status = InsightReportStatus.failed
            report.error_message = str(e)
            report.completed_at = datetime.now(UTC)
            await db.commit()
            logger.exception("insight_report_failed", report_id=report_id, error=str(e))
