# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-FileCopyrightText: 2026 Shreem Seth <shreemseth26@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Redis-backed response cache for dashboard and OTEL endpoints."""

import hashlib
import logging

from redis import asyncio as aioredis
from starlette.requests import Request

from config import settings

logger = logging.getLogger(__name__)

CACHE_PREFIX = "observal-cache"

_redis: aioredis.Redis | None = None


def _request_key_builder(func, namespace="", *, request: Request | None = None, **kwargs):
    """Build cache key from auth identity + path + query string.

    Including a per-user identity component prevents a shared cache from
    serving one authenticated user's response to a different user whose
    request happens to hit the same path and query string (SEC-023).

    Anonymous requests use the literal identity ``anon`` so they can
    still share a cache bucket with each other.
    """
    prefix = f"{CACHE_PREFIX}:{namespace}" if namespace else CACHE_PREFIX
    url = request.url.path if request else func.__name__
    qs = str(request.query_params) if request and request.query_params else ""

    identity = "anon"
    if request:
        auth = request.headers.get("authorization", "")
        if auth.startswith("Bearer "):
            # Hash the token so the raw credential never appears in a cache key.
            identity = hashlib.sha256(auth.encode(), usedforsecurity=False).hexdigest()[:16]

    raw = f"{identity}:{url}?{qs}" if qs else f"{identity}:{url}"
    return f"{prefix}:{hashlib.md5(raw.encode(), usedforsecurity=False).hexdigest()}"


async def init_cache() -> None:
    """Initialize FastAPICache with a Redis backend.

    Uses a separate Redis connection with ``decode_responses=False``
    because fastapi-cache2 stores binary (bytes) values.
    """
    global _redis
    from fastapi_cache import FastAPICache
    from fastapi_cache.backends.redis import RedisBackend

    _redis = aioredis.from_url(
        settings.REDIS_URL,
        encoding="utf-8",
        decode_responses=False,
        socket_connect_timeout=settings.REDIS_SOCKET_TIMEOUT,
        socket_timeout=settings.REDIS_SOCKET_TIMEOUT,
    )
    FastAPICache.init(RedisBackend(_redis), prefix=CACHE_PREFIX, key_builder=_request_key_builder)
    logger.info("FastAPICache initialized (Redis backend, prefix=%s)", CACHE_PREFIX)


async def close_cache() -> None:
    global _redis
    if _redis:
        await _redis.aclose()
        _redis = None


async def invalidate_all() -> int:
    """Delete every key under the cache prefix. Returns count deleted."""
    if not _redis:
        return 0
    cursor, keys = 0, []
    pattern = f"{CACHE_PREFIX}:*"
    while True:
        cursor, batch = await _redis.scan(cursor=cursor, match=pattern, count=500)
        keys.extend(batch)
        if cursor == 0:
            break
    if keys:
        await _redis.delete(*keys)
    logger.info("Cache invalidated: %d keys deleted", len(keys))
    return len(keys)


async def invalidate_namespace(namespace: str) -> int:
    """Delete keys matching a specific namespace."""
    if not _redis:
        return 0
    pattern = f"{CACHE_PREFIX}:{namespace}:*"
    cursor, keys = 0, []
    while True:
        cursor, batch = await _redis.scan(cursor=cursor, match=pattern, count=500)
        keys.extend(batch)
        if cursor == 0:
            break
    if keys:
        await _redis.delete(*keys)
    return len(keys)
