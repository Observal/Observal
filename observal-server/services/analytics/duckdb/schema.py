# SPDX-FileCopyrightText: 2026 Observal contributors
# SPDX-FileCopyrightText: 2026 Srihari <sriharilegend23@gmail.com>
# SPDX-License-Identifier: Apache-2.0
"""Analytics runtime initialization and resource tuning (application side).

The API and worker processes have no direct handle on the DuckDB file; they
push resource tuning to the service container and check its health.
"""

from loguru import logger as optic

import services.analytics.duckdb.client as _client

# Maps enterprise_config keys to DuckDB per-connection pragmas.
# Only whitelisted, non-SQL settings are accepted.
RESOURCE_SETTINGS_MAP: dict[str, tuple[str, str]] = {
    "resource.max_query_memory_mb": ("memory_limit", "mb"),
    "resource.threads": ("threads", ""),
    "resource.temp_directory": ("temp_directory", ""),
}


async def apply_resource_settings(overrides: dict[str, str] | None = None) -> dict[str, str]:
    """Load resource tuning settings and push them to the analytics service.

    Reads from enterprise_config (Postgres) unless *overrides* is supplied.
    Returns the pragma dict that was applied.
    """
    resource_values: dict[str, str] = {}

    if overrides is not None:
        resource_values = overrides
    else:
        try:
            from sqlalchemy import select

            from database import async_session
            from models.enterprise_config import EnterpriseConfig

            async with async_session() as db:
                result = await db.execute(select(EnterpriseConfig).where(EnterpriseConfig.key.like("resource.%")))
                for cfg in result.scalars().all():
                    resource_values[cfg.key] = cfg.value
        except Exception as e:
            optic.warning("could not read resource settings from DB (using defaults): {}", e)

    pragmas: dict[str, str] = {}
    for config_key, (pragma, suffix) in RESOURCE_SETTINGS_MAP.items():
        raw = resource_values.get(config_key)
        if raw is None:
            continue
        value = str(raw).strip()
        if not value:
            continue
        try:
            if suffix == "mb":
                mb = int(value)
                if mb <= 0:
                    continue
                value = f"{mb}MB"
            elif pragma == "threads":
                threads = int(value)
                if threads <= 0:
                    continue
                value = str(threads)
        except (TypeError, ValueError):
            optic.warning("invalid resource setting {}={}, skipping", config_key, raw)
            continue
        pragmas[pragma] = value

    if not pragmas:
        return {}

    await _client._apply_pragmas(pragmas)
    optic.info("DuckDB resource overrides applied: {}", pragmas)
    return pragmas


async def init_analytics() -> None:
    """Initialize the analytics backend from the application side."""
    optic.info("initializing DuckDB analytics runtime settings")

    if not await _client.analytics_health():
        raise RuntimeError(f"DuckDB analytics service unreachable at {_client.ANALYTICS_HTTP}")

    await apply_resource_settings()

    import services.dynamic_settings as ds

    retention_days = await ds.get_int("data.retention_days")
    if retention_days > 0:
        optic.info("DuckDB retention is enforced by the retention job: {} days", retention_days)
    else:
        optic.info("data retention disabled (retention_days=0), data kept indefinitely")
