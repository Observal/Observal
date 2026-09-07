# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: Apache-2.0
"""DuckDB runtime initialization and resource-tuning settings."""

from loguru import logger as optic

import services.duckdb._settings as _settings
import services.duckdb.client as _client

# ── Resource tuning ───────────────────────────────────────────────────────────

# Maps enterprise_config keys to DuckDB SET-able pragmas.
# DuckDB applies memory/thread limits at the connection level rather than per
# query; spill-to-disk is automatic once memory_limit is set.
# Only whitelisted settings are accepted to avoid SQL injection.
RESOURCE_SETTINGS_MAP: dict[str, tuple[str, type]] = {
    "resource.max_query_memory_mb": ("memory_limit", int),
    "resource.threads": ("threads", int),
}


# Re-export for backwards compat (tests and __init__ reference these)
DEFAULT_QUERY_SETTINGS = _settings.DEFAULT_QUERY_SETTINGS
_resource_overrides = _settings._resource_overrides


def _apply_pragmas(overrides: dict[str, str]) -> None:
    """Apply SET pragmas to the live connection (must hold no queries in flight)."""
    with _client._lock:
        con = _client._get_con()
        for pragma, value in overrides.items():
            if pragma == "memory_limit":
                con.execute(f"SET memory_limit = '{int(value)}MB'")
            elif pragma == "threads":
                con.execute(f"SET threads = {int(value)}")
            else:
                optic.warning("no DuckDB mapping for resource setting {}, skipping", pragma)


async def apply_resource_settings(overrides: dict[str, str] | None = None):
    """Load resource tuning settings and apply them to the DuckDB connection.

    Reads from enterprise_config (Postgres) unless *overrides* is supplied.
    """
    import asyncio

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

    if not resource_values:
        return

    new_overrides: dict[str, str] = {}
    for config_key, (pragma, cast) in RESOURCE_SETTINGS_MAP.items():
        raw = resource_values.get(config_key)
        if raw is None:
            continue
        try:
            mb = cast(raw)
            if mb <= 0:
                continue
            new_overrides[pragma] = str(mb)
        except (ValueError, TypeError):
            optic.warning("invalid resource setting {}={}, skipping", config_key, raw)

    _settings._resource_overrides.clear()
    _settings._resource_overrides.update(new_overrides)
    if new_overrides:
        await asyncio.to_thread(_apply_pragmas, new_overrides)
    optic.info("DuckDB resource overrides applied: {}", new_overrides)


async def init_duckdb():
    """Configure DuckDB runtime settings after migrations have run."""
    optic.info("initializing DuckDB runtime settings")

    from services.duckdb.client import duckdb_health

    if not await duckdb_health():
        raise RuntimeError("DuckDB health check failed")

    await apply_resource_settings()

    import services.dynamic_settings as ds

    retention_days = await ds.get_int("data.retention_days")
    if retention_days > 0:
        # DuckDB has no table TTL; retention is enforced by the
        # services.retention cron job (explicit DELETE/UPDATE statements).
        optic.info(
            "data retention configured: {} days (enforced by retention cron; DuckDB has no table TTL)",
            retention_days,
        )
    else:
        optic.info("data retention disabled (retention_days=0), data kept indefinitely")
