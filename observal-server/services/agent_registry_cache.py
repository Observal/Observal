# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""In-memory cache for agent registration lookups at ingest time.

Avoids hitting Postgres on every hook event (70+/sec at scale).
Refreshes every 60 seconds and supports immediate invalidation via Redis pub/sub.
"""

import asyncio
import time
import uuid
from collections import OrderedDict

from loguru import logger as optic
from sqlalchemy import select

from database import async_session
from models.agent import Agent, AgentStatus, AgentVersion
from models.organization import Organization
from models.user import User
from services.redis import get_redis, subscribe

INVALIDATION_CHANNEL = "observal:registry_invalidate"
_REFRESH_INTERVAL = 60  # seconds
_USER_ORG_TTL = 300  # seconds - evict stale user->org mappings
_USER_ORG_MAX_SIZE = 10_000  # max entries before forced eviction

# In-memory caches - replaced atomically (never mutated in-place)
_registered_agents: dict[uuid.UUID, set[str]] = {}  # org_id -> {agent_names}
_org_toggle: dict[uuid.UUID, bool] = {}  # org_id -> registered_agents_only
_user_org_map: OrderedDict[str, tuple[uuid.UUID | None, float]] = OrderedDict()  # user_id -> (org_id, timestamp)

_refresh_task: asyncio.Task | None = None
_subscriber_task: asyncio.Task | None = None


async def _refresh_all() -> None:
    """Refresh all caches from Postgres.

    Uses atomic reference swaps so concurrent readers never see an empty dict.
    """
    global _org_toggle, _registered_agents
    try:
        async with async_session() as session:
            # 1. Refresh org toggle settings
            result = await session.execute(select(Organization.id, Organization.registered_agents_only))
            new_toggle: dict[uuid.UUID, bool] = {}
            for org_id, enabled in result.all():
                new_toggle[org_id] = enabled

            # 2. Refresh registered agent names per org
            # An agent is "registered" when its latest version is approved
            result = await session.execute(
                select(Agent.owner_org_id, Agent.name)
                .join(AgentVersion, Agent.latest_version_id == AgentVersion.id)
                .where(AgentVersion.status == AgentStatus.approved)
                .where(Agent.owner_org_id.isnot(None))
            )
            new_agents: dict[uuid.UUID, set[str]] = {}
            for org_id, name in result.all():
                new_agents.setdefault(org_id, set()).add(name)

        # Atomic swap - readers see old or new, never empty
        _org_toggle = new_toggle
        _registered_agents = new_agents

        optic.debug(
            "registry_cache_refreshed",
            orgs=len(_org_toggle),
            agents_orgs=len(_registered_agents),
        )
    except Exception:
        optic.error("failed to refresh agent registry cache - stale data may be served")


async def _periodic_refresh() -> None:
    """Background task that refreshes the cache every REFRESH_INTERVAL seconds."""
    while True:
        await _refresh_all()
        await asyncio.sleep(_REFRESH_INTERVAL)


async def _listen_for_invalidation() -> None:
    """Subscribe to Redis pub/sub for immediate cache invalidation."""
    try:
        async for _msg in subscribe(INVALIDATION_CHANNEL):
            await _refresh_all()
    except asyncio.CancelledError:
        pass
    except Exception:
        optic.error("registry cache subscriber crashed - cache will not auto-update")


async def start() -> None:
    """Start background refresh and invalidation listener tasks."""
    optic.debug("starting agent registry cache background refresh")
    global _refresh_task, _subscriber_task
    if _refresh_task is None or _refresh_task.done():
        _refresh_task = asyncio.create_task(_periodic_refresh())
    if _subscriber_task is None or _subscriber_task.done():
        _subscriber_task = asyncio.create_task(_listen_for_invalidation())


async def stop() -> None:
    """Cancel background tasks."""
    optic.debug("stopping agent registry cache")
    global _refresh_task, _subscriber_task
    if _refresh_task and not _refresh_task.done():
        _refresh_task.cancel()
        _refresh_task = None
    if _subscriber_task and not _subscriber_task.done():
        _subscriber_task.cancel()
        _subscriber_task = None


def is_toggle_enabled(org_id: uuid.UUID) -> bool:
    """Check if registered-agents-only mode is enabled for this org."""
    return _org_toggle.get(org_id, False)


def is_registered(org_id: uuid.UUID, agent_name: str) -> bool:
    """Check if an agent name is registered (approved) for this org."""
    return agent_name in _registered_agents.get(org_id, set())


async def resolve_user_org(user_id: str) -> uuid.UUID | None:
    """Resolve user_id to org_id, with in-memory + Redis caching.

    In-memory entries expire after _USER_ORG_TTL seconds and the map is
    bounded to _USER_ORG_MAX_SIZE entries (oldest evicted on overflow).
    """
    global _user_org_map

    now = time.monotonic()
    cached_entry = _user_org_map.get(user_id)
    if cached_entry is not None:
        org_id, ts = cached_entry
        if now - ts < _USER_ORG_TTL:
            return org_id
        # Expired - fall through to refresh

    # Try Redis cache first
    r = get_redis()
    cache_key = f"user:{user_id}:org_id"
    try:
        cached = await r.get(cache_key)
        if cached is not None:
            org_id = uuid.UUID(cached) if cached else None
            _user_org_put(user_id, org_id, now)
            return org_id
    except Exception:
        pass

    # Query Postgres
    org_id = None
    try:
        uid = uuid.UUID(user_id)
        async with async_session() as session:
            result = await session.execute(select(User.org_id).where(User.id == uid))
            org_id = result.scalar_one_or_none()
    except Exception:
        pass

    # Cache in Redis (5 min TTL) and in-memory
    _user_org_put(user_id, org_id, now)
    try:
        await r.setex(cache_key, 300, str(org_id) if org_id else "")
    except Exception:
        pass

    return org_id


def _user_org_put(user_id: str, org_id: uuid.UUID | None, now: float) -> None:
    """Insert into _user_org_map with O(1) LRU eviction via OrderedDict."""
    global _user_org_map
    if user_id in _user_org_map:
        _user_org_map.move_to_end(user_id)
    _user_org_map[user_id] = (org_id, now)
    while len(_user_org_map) > _USER_ORG_MAX_SIZE:
        _user_org_map.popitem(last=False)


async def invalidate() -> None:
    """Publish an invalidation signal so all server instances refresh their cache."""
    from services.redis import publish as redis_publish

    await redis_publish(INVALIDATION_CHANNEL, {"action": "invalidate"})
