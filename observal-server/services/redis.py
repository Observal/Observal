"""Redis client and pub/sub helpers for background jobs and subscriptions."""

import json
import logging

import redis.asyncio as aioredis

from config import settings

logger = logging.getLogger(__name__)

_pool: aioredis.ConnectionPool | None = None


def get_pool() -> aioredis.ConnectionPool:
    global _pool
    if _pool is None:
        _pool = aioredis.ConnectionPool.from_url(
            settings.REDIS_URL,
            decode_responses=True,
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
            logger.warning("redis_subscribe_reconnecting", attempt=reconnect_count, max_attempts=max_reconnects, error=str(e))
            await asyncio.sleep(1.0 * reconnect_count)
        finally:
            try:
                await pubsub.unsubscribe(channel)
                await pubsub.close()
            except Exception:
                pass
    logger.error("redis_subscribe_gave_up", max_reconnects=max_reconnects, channel=channel)


async def enqueue_eval(agent_id: str, trace_id: str | None = None):
    """Push an eval job onto the arq queue."""
    r = get_redis()
    job = json.dumps({"function": "run_eval", "agent_id": agent_id, "trace_id": trace_id})
    await r.rpush("arq:queue", job)


async def ping() -> bool:
    """Check Redis connectivity. Returns True if healthy."""
    try:
        r = get_redis()
        return await r.ping()
    except Exception:
        return False


async def close():
    global _pool
    if _pool:
        await _pool.disconnect()
        _pool = None
