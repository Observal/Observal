# SPDX-FileCopyrightText: 2026 Aryan Iyappan <aryaniyappan2006@gmail.com>
# SPDX-FileCopyrightText: 2026 Subramania Raja <dhanpraja231@gmail.com>
# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-FileCopyrightText: 2026 Kaushik Kumar <kaushikrjpm10@gmail.com>
# SPDX-FileCopyrightText: 2026 Lokesh Selvam <lokeshselvam7025@gmail.com>
# SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
# SPDX-FileCopyrightText: 2026 Vishnu Muthiah <vishnu.muthiah04@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""arq background worker: startup/shutdown hooks, job registration, and cron scheduling."""

from arq.cron import cron
from loguru import logger as optic

from jobs.catalog import batch_generate_insights, generate_insight_report, refresh_model_catalog
from jobs.maintenance import maintain_clickhouse, sync_component_sources
from logging_config import setup_logging
from services.alert_evaluator import evaluate_alerts
from services.optic import setup_optic
from services.redis import parse_redis_settings
from services.retention import run_retention_purge

setup_logging()
setup_optic(mode="local")  # Worker always uses local mode for dev visibility


async def startup(ctx: dict):
    from services.insights import configure_insights

    configure_insights()
    optic.info("arq worker started")
    optic.info(
        "worker started with {} functions, {} cron jobs", len(WorkerSettings.functions), len(WorkerSettings.cron_jobs)
    )


async def shutdown(ctx: dict):
    optic.info("arq worker shutting down")
    optic.info("worker shutting down")


class WorkerSettings:
    """arq worker configuration."""

    functions = [
        sync_component_sources,
        evaluate_alerts,
        maintain_clickhouse,
        generate_insight_report,
        batch_generate_insights,
        refresh_model_catalog,
        run_retention_purge,
    ]
    cron_jobs = [
        cron(sync_component_sources, hour={0, 6, 12, 18}),  # Every 6 hours
        cron(evaluate_alerts, second={0}, timeout=55),  # Every minute
        cron(maintain_clickhouse, hour={0, 4, 8, 12, 16, 20}, timeout=120),  # Every 4 hours
        cron(batch_generate_insights, weekday={0}, hour={6}, minute={0}, timeout=300),  # Weekly Monday 6AM
        cron(refresh_model_catalog, hour={0, 6, 12, 18}, minute={5}, timeout=30),  # Every 6 hours (offset)
        cron(
            run_retention_purge, hour={1, 7, 13, 19}, minute={30}, timeout=3600, unique=True
        ),  # Every 6 hours (retention)
    ]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = parse_redis_settings()
    max_jobs = 15
    job_timeout = 600  # 10 min (V2 insights with facet extraction needs more time)
