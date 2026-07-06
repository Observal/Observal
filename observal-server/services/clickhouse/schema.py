# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: Apache-2.0
"""ClickHouse runtime initialization and resource-tuning settings."""

from loguru import logger as optic

import services.clickhouse._settings as _ch_settings
import services.clickhouse.client as _client

# ── Resource tuning ───────────────────────────────────────────────────────────

# Maps enterprise_config keys to ClickHouse SET-able settings.
# Only whitelisted settings are accepted to avoid SQL injection.
RESOURCE_SETTINGS_MAP: dict[str, tuple[str, type]] = {
    "resource.max_query_memory_mb": ("max_memory_usage", int),
    "resource.group_by_spill_mb": ("max_bytes_before_external_group_by", int),
    "resource.sort_spill_mb": ("max_bytes_before_external_sort", int),
    "resource.join_memory_mb": ("max_bytes_in_join", int),
}


# Re-export for backwards compat (tests and __init__ reference these)
DEFAULT_QUERY_SETTINGS = _ch_settings.DEFAULT_QUERY_SETTINGS
_resource_overrides = _ch_settings._resource_overrides


async def apply_resource_settings(overrides: dict[str, str] | None = None):
    """Load resource tuning settings and inject them into every ClickHouse query.

    Reads from enterprise_config (Postgres) unless *overrides* is supplied.
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

    if not resource_values:
        return

    new_overrides: dict[str, str] = {}
    for config_key, (ch_setting, cast) in RESOURCE_SETTINGS_MAP.items():
        raw = resource_values.get(config_key)
        if raw is None:
            continue
        try:
            mb = cast(raw)
            if mb <= 0:
                continue
            new_overrides[ch_setting] = str(mb * 1_000_000)
        except (ValueError, TypeError):
            optic.warning("invalid resource setting {}={}, skipping", config_key, raw)

    _ch_settings._resource_overrides.clear()
    _ch_settings._resource_overrides.update(new_overrides)
    optic.info("ClickHouse resource overrides applied: {}", new_overrides)


async def _materialize_if_needed():
    """Conditionally materialize projection and indexes on session_events.

    Only runs MATERIALIZE commands when parts exist that lack the projection
    or indexes. Avoids creating new mutations on every server restart.
    """
    try:
        r = await _client._query(
            "SELECT count() AS cnt FROM system.parts "
            "WHERE table = 'session_events' AND database = currentDatabase() "
            "AND active AND NOT has(projections, 'proj_session_view') "
            "FORMAT JSON"
        )
        if r.status_code == 200:
            data = r.json().get("data", [{}])
            if int(data[0].get("cnt", 0)) > 0:
                await _client._query("ALTER TABLE session_events MATERIALIZE PROJECTION proj_session_view")
                optic.info("materialized proj_session_view projection on existing parts")
    except Exception as e:
        optic.warning("could not check projection status: {}", e)

    for idx_name in ("idx_se_event_type", "idx_se_parent_session_id"):
        try:
            r = await _client._query(
                "SELECT count() AS cnt FROM system.parts "
                "WHERE table = 'session_events' AND database = currentDatabase() "
                f"AND active AND NOT has(data_skipping_indices, '{idx_name}') "
                "FORMAT JSON"
            )
            if r.status_code == 200:
                data = r.json().get("data", [{}])
                if int(data[0].get("cnt", 0)) > 0:
                    await _client._query(f"ALTER TABLE session_events MATERIALIZE INDEX {idx_name}")
                    optic.info("materialized index {} on existing parts", idx_name)
        except Exception as e:
            optic.warning("could not check index {} status: {}", idx_name, e)


async def init_clickhouse():
    """Configure ClickHouse runtime settings after migrations have run."""
    optic.info("initializing ClickHouse runtime settings")

    from services.clickhouse.client import clickhouse_health

    if not await clickhouse_health():
        raise RuntimeError(f"ClickHouse unreachable at {_client.CLICKHOUSE_HTTP}")

    await _materialize_if_needed()
    await apply_resource_settings()

    import services.dynamic_settings as ds

    retention_days = await ds.get_int("data.retention_days")
    if retention_days > 0:
        ttl_stmts = [
            f"ALTER TABLE session_events MODIFY TTL toDate(timestamp) + INTERVAL {retention_days} DAY",
        ]
        applied = 0
        for stmt in ttl_stmts:
            try:
                await _client._query(stmt)
                applied += 1
            except Exception as e:
                optic.warning("TTL statement failed: {}", e)
        if applied == len(ttl_stmts):
            optic.info("ClickHouse retention configured: {} days across all tables", retention_days)
        else:
            optic.warning(
                "retention only applied to {}/{} tables - some data may not auto-expire", applied, len(ttl_stmts)
            )
    else:
        optic.info("data retention disabled (retention_days=0), data kept indefinitely")
