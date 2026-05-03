"""PostgreSQL-backed session metadata cache for incremental insight reports."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import structlog
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from models.insight_session_meta import InsightSessionMeta
from services.clickhouse import _query

logger = structlog.get_logger(__name__)

# Subquery pattern (same as metrics.py)
_SESSION_META_QUERY = """
    SELECT
        LogAttributes['session.id'] AS session_id,
        min(Timestamp) AS first_event,
        max(Timestamp) AS last_event,
        dateDiff('second', min(Timestamp), max(Timestamp)) AS duration_seconds,
        count() AS event_count,
        greatest(
            countIf(LogAttributes['event.name'] = 'user_prompt'),
            countIf(LogAttributes['event.name'] = 'hook_userpromptsubmit')
        ) AS prompt_count,
        greatest(
            countIf(LogAttributes['event.name'] = 'tool_result'),
            countIf(LogAttributes['event.name'] = 'hook_posttooluse')
        ) AS tool_call_count,
        sum(toUInt64OrZero(LogAttributes['input_tokens'])) AS input_tokens,
        sum(toUInt64OrZero(LogAttributes['output_tokens'])) AS output_tokens,
        sum(toUInt64OrZero(LogAttributes['cache_read_tokens'])) AS cache_read_tokens,
        sum(toUInt64OrZero(LogAttributes['cache_creation_tokens'])) AS cache_write_tokens,
        anyIf(LogAttributes['model'], LogAttributes['model'] != '') AS model,
        anyIf(LogAttributes['user.id'], LogAttributes['user.id'] != '') AS user_id,
        anyIf(LogAttributes['user.name'], LogAttributes['user.name'] != '') AS user_name,
        anyIf(LogAttributes['stop_reason'], LogAttributes['stop_reason'] != '') AS stop_reason,
        anyIf(LogAttributes['platform'], LogAttributes['platform'] != '') AS platform,
        countIf(LogAttributes['error'] != '') AS error_count
    FROM otel_logs
    WHERE LogAttributes['session.id'] IN ({session_ids})
      AND Timestamp >= {{t_start:String}}
      AND Timestamp <= {{t_end:String}}
    GROUP BY session_id
    FORMAT JSON
"""


async def load_cached_metas(db: AsyncSession, agent_id: uuid.UUID, session_ids: list[str]) -> dict[str, dict]:
    """Load cached session metadata from PostgreSQL."""
    if not session_ids:
        return {}

    stmt = select(InsightSessionMeta).where(
        InsightSessionMeta.agent_id == agent_id,
        InsightSessionMeta.session_id.in_(session_ids),
    )
    result = await db.execute(stmt)
    rows = result.scalars().all()
    return {row.session_id: row.meta for row in rows}


async def store_metas(db: AsyncSession, agent_id: uuid.UUID, metas: dict[str, dict]) -> None:
    """Store computed session metadata in PostgreSQL (upsert)."""
    if not metas:
        return

    now = datetime.now(UTC)
    for session_id, meta in metas.items():
        stmt = pg_insert(InsightSessionMeta).values(
            id=uuid.uuid4(),
            agent_id=agent_id,
            session_id=session_id,
            computed_at=now,
            meta=meta,
        ).on_conflict_do_update(
            constraint="uq_session_meta_agent_session",
            set_={"meta": meta, "computed_at": now},
        )
        await db.execute(stmt)
    await db.flush()


async def compute_session_metas_from_clickhouse(
    session_ids: list[str], start: str, end: str
) -> dict[str, dict]:
    """Query ClickHouse for session-level metadata for given session IDs."""
    if not session_ids:
        return {}

    # Build IN clause with quoted session IDs
    ids_str = ", ".join(f"'{sid}'" for sid in session_ids)
    sql = _SESSION_META_QUERY.format(session_ids=ids_str)
    params = {"param_t_start": start, "param_t_end": end}

    try:
        r = await _query(sql, params)
        r.raise_for_status()
        rows = r.json().get("data", [])
        return {row["session_id"]: row for row in rows}
    except Exception as e:
        logger.error("session_meta_clickhouse_failed", error=str(e))
        return {}


async def get_or_compute_metas(
    db: AsyncSession,
    agent_id: uuid.UUID,
    session_ids: list[str],
    start: str,
    end: str,
) -> dict[str, dict]:
    """Load cached metas, compute missing ones from ClickHouse, store and return all."""
    cached = await load_cached_metas(db, agent_id, session_ids)
    uncached_ids = [sid for sid in session_ids if sid not in cached]

    if uncached_ids:
        computed = await compute_session_metas_from_clickhouse(uncached_ids, start, end)
        if computed:
            await store_metas(db, agent_id, computed)
            cached.update(computed)

    return cached
