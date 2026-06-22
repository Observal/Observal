# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Insights background jobs."""

from loguru import logger as optic


async def generate_insight_report(ctx: dict, report_id: str):
    """Background job: generate an insight report for an agent."""
    optic.info("insight_report_started", report_id=report_id)
    try:
        from services.insights import run_single_report

        await run_single_report(report_id)
    except Exception as e:
        optic.error("insight_report_job_failed", report_id=report_id, error=str(e))


async def batch_generate_insights(ctx: dict):
    """Cron job: discover agents needing reports and queue generation."""
    optic.debug("batch_generate_insights")
    try:
        from services.insights import discover_and_queue_reports

        queued = await discover_and_queue_reports()
        if queued > 0:
            optic.info("insight_batch_queued_reports", count=queued)
    except Exception as e:
        optic.error("insight_batch_failed", error=str(e))
