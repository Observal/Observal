# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Catalog and insights background jobs."""

from loguru import logger as optic


async def generate_insight_report(ctx: dict, report_id: str):
    """Background job: generate an insight report for an agent."""
    optic.debug("generate_insight_report")
    from services.insights import INSIGHTS_AVAILABLE

    if not INSIGHTS_AVAILABLE:
        optic.warning("insight_report_skipped", reason="package not installed")
        return

    optic.info("insight_report_started", report_id=report_id)
    try:
        from services.insights import _run_single_report

        if _run_single_report is None:
            optic.warning("insight_report_skipped", reason="license not valid")
            return
        await _run_single_report(report_id)
    except Exception as e:
        optic.error("insight_report_job_failed", report_id=report_id, error=str(e))


async def batch_generate_insights(ctx: dict):
    """Cron job: discover agents needing reports and queue generation."""
    optic.debug("batch_generate_insights")
    from services.insights import INSIGHTS_AVAILABLE

    if not INSIGHTS_AVAILABLE:
        return

    from services.insights import _discover_and_queue

    if _discover_and_queue is None:
        return

    try:
        queued = await _discover_and_queue()
        if queued > 0:
            optic.info("insight_batch_queued_reports", count=queued)
    except Exception as e:
        optic.error("insight_batch_failed", error=str(e))


async def refresh_model_catalog(ctx: dict):
    """Cron job: pre-warm the model catalog so user requests never hit a cold cache."""
    optic.debug("refresh_model_catalog")
    from services.model_catalog import get_catalog

    try:
        cat = await get_catalog(force_refresh=True)
        optic.info(
            "model_catalog_prewarm",
            source=cat.source,
            count=cat.model_count,
            degraded=cat.degraded,
        )
    except Exception as e:
        optic.warning("model_catalog_prewarm_failed", error=str(e))
