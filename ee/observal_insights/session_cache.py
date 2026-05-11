"""Session metadata caching layer for Agent Insights.

Loads session metadata from ClickHouse and caches processed results in
PostgreSQL via the InsightSessionMeta model. This avoids re-querying
ClickHouse for the same session data across report regenerations.

V3: Primary path queries `session_events` table using `agent_id`.
Fallback path queries `otel_logs` using `agent_name` for agents that
haven't migrated to the new event pipeline.
"""

from __future__ import annotations

from datetime import UTC, datetime

import structlog

from ._deps import get_meta_cache_model, get_query

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Primary path: session_events table (V3)
# ---------------------------------------------------------------------------


async def fetch_session_metas_from_events(
    agent_id: str,
    period_start: str,
    period_end: str,
) -> list[dict]:
    """Fetch session metadata from session_stats_agg (V3 primary path).

    Reads from the pre-aggregated AggregatingMergeTree table instead of
    scanning session_events FINAL with JSONExtract.  The session_stats_mv
    materialized view keeps session_stats_agg in sync with every INSERT
    into session_events, so no FINAL is needed here.

    Both primary sessions (directly attributed to this agent) and subagent
    sessions (parent attributed to this agent) are returned via a UNION ALL
    over session_stats_agg — no raw session_events scan.

    Args:
        agent_id: The agent UUID.
        period_start: ISO timestamp for period start.
        period_end: ISO timestamp for period end.

    Returns:
        List of session metadata dicts from ClickHouse.
    """
    query = get_query()

    sql = """
        SELECT
            session_id,
            start_time,
            end_time,
            dateDiff('second',
                if(start_time > '1970-01-02' AND start_time < '2099-01-01',
                   start_time, end_time),
                if(end_time > '1970-01-02' AND end_time < '2099-01-01',
                   end_time, start_time)
            ) AS duration_seconds,
            event_count,
            prompt_count,
            tool_call_count,
            tool_result_count,
            input_tokens,
            output_tokens,
            cache_read_tokens,
            cache_write_tokens,
            total_credits,
            ide,
            user_id,
            parent_session_id
        FROM (
            -- Primary: sessions directly attributed to this agent (pre-aggregated)
            SELECT
                session_id,
                min(first_event_time) AS start_time,
                max(last_event_time)  AS end_time,
                sum(event_count)      AS event_count,
                sum(prompt_count)     AS prompt_count,
                sum(tool_call_count)  AS tool_call_count,
                sum(tool_result_count) AS tool_result_count,
                sum(input_tokens)     AS input_tokens,
                sum(output_tokens)    AS output_tokens,
                sum(cache_read_tokens) AS cache_read_tokens,
                sum(cache_write_tokens) AS cache_write_tokens,
                sum(total_credits)    AS total_credits,
                anyLast(ide)          AS ide,
                anyLast(user_id)      AS user_id,
                anyLast(parent_session_id) AS parent_session_id
            FROM (SELECT * FROM session_stats_agg WHERE agent_id = {agent_id:String})
            GROUP BY session_id

            UNION ALL

            -- Subagent sessions: parent attributed to this agent but the
            -- subagent row has a different (or empty) agent_id.
            SELECT
                session_id,
                min(first_event_time) AS start_time,
                max(last_event_time)  AS end_time,
                sum(event_count)      AS event_count,
                sum(prompt_count)     AS prompt_count,
                sum(tool_call_count)  AS tool_call_count,
                sum(tool_result_count) AS tool_result_count,
                sum(input_tokens)     AS input_tokens,
                sum(output_tokens)    AS output_tokens,
                sum(cache_read_tokens) AS cache_read_tokens,
                sum(cache_write_tokens) AS cache_write_tokens,
                sum(total_credits)    AS total_credits,
                anyLast(ide)          AS ide,
                anyLast(user_id)      AS user_id,
                anyLast(parent_session_id) AS parent_session_id
            FROM (
                SELECT * FROM session_stats_agg
                WHERE parent_session_id IN (
                    SELECT session_id
                    FROM (SELECT * FROM session_stats_agg WHERE agent_id = {agent_id:String})
                    GROUP BY session_id
                )
                AND (agent_id != {agent_id:String} OR agent_id = '')
            )
            GROUP BY session_id
        )
        WHERE event_count >= 2
          AND end_time BETWEEN {t_start:String} AND {t_end:String}
        ORDER BY start_time
        FORMAT JSON
    """
    params = {
        "param_agent_id": agent_id,
        "param_t_start": period_start,
        "param_t_end": period_end,
    }

    try:
        r = await query(sql, params)
        r.raise_for_status()
        return r.json().get("data", [])
    except Exception as e:
        logger.error(
            "session_meta_fetch_from_events_failed",
            agent_id=agent_id,
            error=str(e),
        )
        return []


async def get_session_last_event_time(session_id: str) -> datetime | None:
    """Get the timestamp of the last event in a session (for facet staleness).

    Args:
        session_id: The session UUID.

    Returns:
        The datetime of the last event, or None if not found.
    """
    query = get_query()
    sql = """
        SELECT max(timestamp) AS last_event
        FROM session_events FINAL
        WHERE session_id = {sid:String}
        FORMAT JSON
    """
    params = {"param_sid": session_id}

    try:
        r = await query(sql, params)
        r.raise_for_status()
        data = r.json().get("data", [])
        if data and data[0].get("last_event"):
            ts_str = data[0]["last_event"]
            # Parse ClickHouse timestamp format
            for fmt in (
                "%Y-%m-%d %H:%M:%S.%f",
                "%Y-%m-%dT%H:%M:%S.%fZ",
                "%Y-%m-%dT%H:%M:%S.%f",
                "%Y-%m-%d %H:%M:%S",
                "%Y-%m-%dT%H:%M:%SZ",
            ):
                try:
                    return datetime.strptime(ts_str[:26], fmt).replace(tzinfo=UTC)
                except ValueError:
                    continue
        return None
    except Exception as e:
        logger.warning("session_last_event_time_failed", session_id=session_id, error=str(e))
        return None


# ---------------------------------------------------------------------------
# Fallback path: otel_logs table (legacy)
# ---------------------------------------------------------------------------


async def fetch_session_metas(
    agent_name: str,
    period_start: str,
    period_end: str,
) -> list[dict]:
    """Fetch session metadata from ClickHouse otel_logs (legacy fallback).

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


# ---------------------------------------------------------------------------
# Cache layer (PostgreSQL)
# ---------------------------------------------------------------------------


async def load_cached_metas(
    agent_id: str,
    period_start: str,
    period_end: str,
    db,
) -> dict[str, dict] | None:
    """Load cached session metadata from PostgreSQL.

    Args:
        agent_id: The agent UUID (as string).
        period_start: ISO timestamp for period start.
        period_end: ISO timestamp for period end.
        db: An AsyncSession instance.

    Returns:
        Dict mapping session_id -> metadata, or None if no cache exists.
    """
    CacheModel = get_meta_cache_model()

    from sqlalchemy import select

    stmt = (
        select(CacheModel)
        .where(CacheModel.agent_id == agent_id)
        .where(CacheModel.period_start == period_start)
        .where(CacheModel.period_end == period_end)
    )
    result = await db.execute(stmt)
    row = result.scalar_one_or_none()

    if row is None:
        return None

    return row.session_metas


async def store_cached_metas(
    agent_id: str,
    period_start: str,
    period_end: str,
    session_metas: dict[str, dict],
    db,
) -> None:
    """Persist session metadata cache to PostgreSQL.

    Args:
        agent_id: The agent UUID (as string).
        period_start: ISO timestamp for period start.
        period_end: ISO timestamp for period end.
        session_metas: Dict mapping session_id -> metadata.
        db: An AsyncSession instance.
    """
    CacheModel = get_meta_cache_model()

    from sqlalchemy import select

    stmt = (
        select(CacheModel)
        .where(CacheModel.agent_id == agent_id)
        .where(CacheModel.period_start == period_start)
        .where(CacheModel.period_end == period_end)
    )
    result = await db.execute(stmt)
    existing = result.scalar_one_or_none()

    if existing:
        existing.session_metas = session_metas
        existing.updated_at = datetime.now(UTC)
    else:
        record = CacheModel(
            agent_id=agent_id,
            period_start=period_start,
            period_end=period_end,
            session_metas=session_metas,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        db.add(record)

    await db.flush()


# ---------------------------------------------------------------------------
# Main entry point: dual-source with fallback
# ---------------------------------------------------------------------------


async def get_session_metas(
    agent_id: str,
    agent_name: str = "",
    period_start: str = "",
    period_end: str = "",
    db=None,
    use_cache: bool = True,
) -> dict[str, dict]:
    """Get session metadata, using cache when available.

    V3: Tries session_events first (using agent_id), falls back to
    otel_logs (using agent_name) if no results are found.

    Args:
        agent_id: The agent UUID (used for session_events query and cache key).
        agent_name: The agent registry name (used for otel_logs fallback).
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

    # V3 primary path: try session_events using agent_id
    rows = []
    if agent_id:
        rows = await fetch_session_metas_from_events(agent_id, period_start, period_end)

    # Fallback: otel_logs using agent_name
    if not rows and agent_name:
        logger.info(
            "session_metas_falling_back_to_otel_logs",
            agent_id=agent_id,
            agent_name=agent_name,
        )
        rows = await fetch_session_metas(agent_name, period_start, period_end)

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
