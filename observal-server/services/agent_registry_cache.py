"""In-memory cache for agent registration lookups at ingest time.

Avoids hitting Postgres on every hook event (70+/sec at scale).
Refreshes every 60 seconds and supports immediate invalidation via Redis pub/sub.
"""

import asyncio
import uuid

import structlog
from sqlalchemy import select

from database import async_session
from models.agent import Agent, AgentStatus, AgentVersion
from models.organization import Organization
from models.user import User
from services.redis import get_redis, subscribe

logger = structlog.get_logger(__name__)

INVALIDATION_CHANNEL = "observal:registry_invalidate"
_REFRESH_INTERVAL = 60  # seconds

# In-memory caches
_registered_agents: dict[uuid.UUID, set[str]] = {}  # org_id -> {agent_names}
_org_toggle: dict[uuid.UUID, bool] = {}  # org_id -> registered_agents_only
_user_org_map: dict[str, uuid.UUID | None] = {}  # user_id string -> org_id

_refresh_task: asyncio.Task | None = None
_subscriber_task: asyncio.Task | None = None


async def _refresh_all() -> None:
    """Refresh all caches from Postgres."""
    try:
        async with async_session() as session:
            # 1. Refresh org toggle settings
            result = await session.execute(select(Organization.id, Organization.registered_agents_only))
            new_toggle: dict[uuid.UUID, bool] = {}
            for org_id, enabled in result.all():
                new_toggle[org_id] = enabled
            _org_toggle.clear()
            _org_toggle.update(new_toggle)

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
            _registered_agents.clear()
            _registered_agents.update(new_agents)

        logger.debug(
            "registry_cache_refreshed",
            orgs=len(_org_toggle),
            agents_orgs=len(_registered_agents),
        )
    except Exception:
        logger.exception("registry_cache_refresh_failed")


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
        logger.exception("registry_cache_subscriber_error")


async def start() -> None:
    """Start background refresh and invalidation listener tasks."""
    global _refresh_task, _subscriber_task
    if _refresh_task is None or _refresh_task.done():
        _refresh_task = asyncio.create_task(_periodic_refresh())
    if _subscriber_task is None or _subscriber_task.done():
        _subscriber_task = asyncio.create_task(_listen_for_invalidation())


async def stop() -> None:
    """Cancel background tasks."""
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
    """Resolve user_id to org_id, with in-memory + Redis caching."""
    if user_id in _user_org_map:
        return _user_org_map[user_id]

    # Try Redis cache first
    r = get_redis()
    cache_key = f"user:{user_id}:org_id"
    try:
        cached = await r.get(cache_key)
        if cached is not None:
            org_id = uuid.UUID(cached) if cached else None
            _user_org_map[user_id] = org_id
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
    _user_org_map[user_id] = org_id
    try:
        await r.setex(cache_key, 300, str(org_id) if org_id else "")
    except Exception:
        pass

    return org_id


async def invalidate() -> None:
    """Publish an invalidation signal so all server instances refresh their cache."""
    from services.redis import publish as redis_publish

    await redis_publish(INVALIDATION_CHANNEL, {"action": "invalidate"})
