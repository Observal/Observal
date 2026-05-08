"""Session metadata caching layer for Agent Insights.

Loads session metadata from ClickHouse and caches processed results in
PostgreSQL via the InsightSessionMeta model. This avoids re-querying
ClickHouse for the same session data across report regenerations.
"""

from __future__ import annotations

from datetime import UTC, datetime

import structlog

from ._deps import get_meta_model, get_query

logger = structlog.get_logger(__name__)


async def fetch_session_metas(
    agent_name: str,
    period_start: str,
    period_end: str,
) -> list[dict]:
    """Fetch session metadata from ClickHouse for a given agent and time range.

    Args:
        agent_name: The agent registry name (matches agent_type or agent_name in otel_logs).
        period_start: ISO timestamp for period start.
        period_end: ISO timestamp for period end.

    Returns:
        List of session metadata dicts from ClickHouse.
    """
    query = get_query()

    sql = """
        SELECT
            LogAttributes['session.id'] AS session_id,
            min(Timestamp) AS start_time,
            max(Timestamp) AS end_time,
            dateDiff('second', min(Timestamp), max(Timestamp)) AS duration_seconds,
            count() AS event_count,
            countIf(LogAttributes['event.name'] IN ('tool_result', 'hook_posttooluse')) AS tool_call_count,
            countIf(LogAttributes['error'] != '') AS error_count,
            any(LogAttributes['model']) AS model,
            any(LogAttributes['platform']) AS platform,
            any(LogAttributes['user_id']) AS user_id,
            any(LogAttributes['user_name']) AS user_name,
            any(LogAttributes['cwd']) AS cwd,
            any(LogAttributes['stop_reason']) AS stop_reason,
            sumIf(
                toUInt64OrZero(LogAttributes['input_tokens']),
                LogAttributes['event.name'] = 'api_request'
            ) AS input_tokens,
            sumIf(
                toUInt64OrZero(LogAttributes['output_tokens']),
                LogAttributes['event.name'] = 'api_request'
            ) AS output_tokens,
            sumIf(
                toUInt64OrZero(LogAttributes['cache_read_tokens']),
                LogAttributes['event.name'] = 'api_request'
            ) AS cache_read_tokens,
            sumIf(
                toUInt64OrZero(LogAttributes['cache_write_tokens']),
                LogAttributes['event.name'] = 'api_request'
            ) AS cache_write_tokens
        FROM otel_logs
        WHERE (LogAttributes['agent_type'] = {aname:String}
               OR LogAttributes['agent_name'] = {aname:String})
          AND Timestamp >= {t_start:String}
          AND Timestamp <= {t_end:String}
          AND LogAttributes['session.id'] != ''
        GROUP BY session_id
        HAVING event_count >= 2
        ORDER BY start_time
        FORMAT JSON
    """
    params = {
        "param_aname": agent_name,
        "param_t_start": period_start,
        "param_t_end": period_end,
    }

    try:
        r = await query(sql, params)
        r.raise_for_status()
        data = r.json().get("data", [])
        return data
    except Exception as e:
        logger.error(
            "session_meta_fetch_failed",
            agent_name=agent_name,
            error=str(e),
        )
        return []


async def load_cached_metas(
    agent_id: str,
    period_start: str,
    period_end: str,
    db,
) -> dict[str, dict] | None:
    """Load cached session metadata from PostgreSQL.

    The InsightSessionMeta model stores one row per session. We load all
    cached sessions for the agent and return those whose start_time falls
    within the requested period.

    Args:
        agent_id: The agent UUID (as string).
        period_start: ISO timestamp for period start.
        period_end: ISO timestamp for period end.
        db: An AsyncSession instance.

    Returns:
        Dict mapping session_id -> metadata, or None if no cache exists.
    """
    MetaModel = get_meta_model()

    from sqlalchemy import select

    stmt = select(MetaModel).where(MetaModel.agent_id == agent_id)
    result = await db.execute(stmt)
    rows = result.scalars().all()

    if not rows:
        return None

    metas: dict[str, dict] = {}
    for row in rows:
        meta = row.meta if hasattr(row, "meta") else None
        if not meta:
            continue
        metas[row.session_id] = meta

    return metas if metas else None


async def store_cached_metas(
    agent_id: str,
    period_start: str,
    period_end: str,
    session_metas: dict[str, dict],
    db,
) -> None:
    """Persist session metadata cache to PostgreSQL.

    Stores one row per session in InsightSessionMeta. Upserts by
    (agent_id, session_id) unique constraint.

    Args:
        agent_id: The agent UUID (as string).
        period_start: ISO timestamp for period start.
        period_end: ISO timestamp for period end.
        session_metas: Dict mapping session_id -> metadata.
        db: An AsyncSession instance.
    """
    MetaModel = get_meta_model()

    from sqlalchemy import select

    for session_id, meta in session_metas.items():
        stmt = select(MetaModel).where(MetaModel.agent_id == agent_id).where(MetaModel.session_id == session_id)
        result = await db.execute(stmt)
        existing = result.scalar_one_or_none()

        if existing:
            existing.meta = meta
            existing.computed_at = datetime.now(UTC)
        else:
            record = MetaModel(
                agent_id=agent_id,
                session_id=session_id,
                computed_at=datetime.now(UTC),
                meta=meta,
            )
            db.add(record)

    await db.flush()


async def get_session_metas(
    agent_id: str,
    agent_name: str = "",
    period_start: str = "",
    period_end: str = "",
    db=None,
    use_cache: bool = True,
) -> dict[str, dict]:
    """Get session metadata, using cache when available.

    Fetches from ClickHouse and optionally caches in PostgreSQL for
    subsequent report regenerations.

    Args:
        agent_id: The agent UUID (used for cache key).
        agent_name: The agent registry name (used for ClickHouse query).
        period_start: ISO timestamp for period start.
        period_end: ISO timestamp for period end.
        db: Optional AsyncSession for caching. If None, caching is skipped.
        use_cache: Whether to check/store cache.

    Returns:
        Dict mapping session_id -> metadata dict.
    """
    # Try cache first
    if use_cache and db is not None:
        try:
            cached = await load_cached_metas(agent_id, period_start, period_end, db)
            if cached:
                logger.debug(
                    "session_metas_cache_hit",
                    agent_id=agent_id,
                    count=len(cached),
                )
                return cached
        except Exception as e:
            logger.warning("session_metas_cache_load_failed", error=str(e))

    # Fetch from ClickHouse using agent_name for the query
    rows = await fetch_session_metas(agent_name or agent_id, period_start, period_end)
    if not rows:
        return {}

    # Index by session_id
    metas: dict[str, dict] = {}
    for row in rows:
        sid = row.get("session_id", "")
        if sid:
            metas[sid] = row

    logger.info(
        "session_metas_fetched",
        agent_id=agent_id,
        count=len(metas),
    )

    # Store in cache
    if use_cache and db is not None and metas:
        try:
            await store_cached_metas(agent_id, period_start, period_end, metas, db)
        except Exception as e:
            logger.warning("session_metas_cache_store_failed", error=str(e))

    return metas
