"""Redis client and pub/sub helpers for background jobs and subscriptions."""

import json
from urllib.parse import urlparse

import redis.asyncio as aioredis
import structlog
from arq import create_pool as arq_create_pool
from arq.connections import ArqRedis, RedisSettings

from config import settings

logger = structlog.get_logger(__name__)

_pool: aioredis.ConnectionPool | None = None


def get_pool() -> aioredis.ConnectionPool:
    global _pool
    if _pool is None:
        _pool = aioredis.ConnectionPool.from_url(
            settings.REDIS_URL,
            decode_responses=True,
            max_connections=settings.REDIS_MAX_CONNECTIONS,
            socket_connect_timeout=settings.REDIS_SOCKET_TIMEOUT,
            socket_timeout=settings.REDIS_SOCKET_TIMEOUT,
        )
    return _pool


def get_redis() -> aioredis.Redis:
    return aioredis.Redis(connection_pool=get_pool())


async def publish(channel: str, data: dict):
    """Publish a message to a Redis pub/sub channel (for GraphQL subscriptions)."""
    import asyncio

    r = get_redis()
    attempts = 0
    max_attempts = 3
    while attempts < max_attempts:
        try:
            await r.publish(channel, json.dumps(data))
            return
        except (ConnectionError, OSError) as e:
            attempts += 1
            if attempts >= max_attempts:
                logger.warning("redis_publish_failed", attempts=max_attempts, error=str(e))
                return
            logger.debug("redis_publish_retry", attempt=attempts, error=str(e))
            await asyncio.sleep(0.5 * attempts)


async def subscribe(channel: str):
    """Subscribe to a Redis pub/sub channel. Yields parsed messages. Auto-reconnects."""
    import asyncio

    max_reconnects = 5
    reconnect_count = 0
    while reconnect_count < max_reconnects:
        r = get_redis()
        pubsub = r.pubsub()
        try:
            await pubsub.subscribe(channel)
            async for message in pubsub.listen():
                reconnect_count = 0  # Reset on successful message
                if message["type"] == "message":
                    try:
                        yield json.loads(message["data"])
                    except (json.JSONDecodeError, TypeError):
                        continue
        except (ConnectionError, OSError) as e:
            reconnect_count += 1
            logger.warning(
                "redis_subscribe_reconnecting", attempt=reconnect_count, max_attempts=max_reconnects, error=str(e)
            )
            await asyncio.sleep(1.0 * reconnect_count)
        finally:
            try:
                await pubsub.unsubscribe(channel)
                await pubsub.close()
            except Exception:
                pass
    logger.error("redis_subscribe_gave_up", max_reconnects=max_reconnects, channel=channel)


def parse_redis_settings() -> RedisSettings:
    """Parse REDIS_URL into arq RedisSettings."""
    parsed = urlparse(settings.REDIS_URL)
    return RedisSettings(
        host=parsed.hostname or "localhost",
        port=parsed.port or 6379,
        password=parsed.password,
        database=int(parsed.path.lstrip("/") or 0),
    )


_arq_pool: ArqRedis | None = None


async def _get_arq_pool() -> ArqRedis:
    global _arq_pool
    if _arq_pool is None:
        _arq_pool = await arq_create_pool(parse_redis_settings())
    return _arq_pool


async def enqueue_eval(agent_id: str, trace_id: str | None = None):
    """Enqueue an eval job via arq with dedup."""
    pool = await _get_arq_pool()
    await pool.enqueue_job(
        "run_eval",
        agent_id,
        trace_id,
        _job_id=f"eval:{agent_id}:{trace_id or 'all'}",
    )


async def ping() -> bool:
    """Check Redis connectivity. Returns True if healthy."""
    try:
        r = get_redis()
        return await r.ping()
    except Exception:
        return False


async def close():
    global _pool, _arq_pool
    if _arq_pool:
        await _arq_pool.close()
        _arq_pool = None
    if _pool:
        await _pool.disconnect()
        _pool = None
