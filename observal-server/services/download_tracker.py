import hashlib
import logging
import uuid
from datetime import UTC, datetime

from fastapi import Request
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from models.agent import Agent
from models.download import AgentDownloadRecord, ComponentDownloadRecord

logger = logging.getLogger(__name__)


def _anonymous_fingerprint(request: Request) -> str:
    """Generate fingerprint from IP + user-agent for anonymous deduplication."""
    ip = request.client.host if request.client else "unknown"
    ua = request.headers.get("user-agent", "")
    return hashlib.sha256(f"{ip}:{ua}".encode()).hexdigest()


async def record_agent_download(
    agent_id: uuid.UUID,
    user_id: uuid.UUID | None,
    source: str,
    ide: str | None,
    request: Request,
    db: AsyncSession,
) -> bool:
    """Record an agent download with deduplication. Returns True if new download, False if duplicate."""
    fingerprint = _anonymous_fingerprint(request) if user_id is None else None

    record = AgentDownloadRecord(
        agent_id=agent_id,
        user_id=user_id,
        fingerprint=fingerprint,
        source=source,
        ide=ide,
    )
    # Use a savepoint so that IntegrityError rollback doesn't expire
    # all objects in the outer session (which causes MissingGreenlet
    # when the caller later accesses ORM attributes in sync context).
    try:
        async with db.begin_nested():
            db.add(record)
            await db.flush()
        # Update aggregate counts (outside savepoint, still in main txn)
        await _update_agent_counts(agent_id, db)
        return True
    except IntegrityError:
        logger.debug("Duplicate download for agent %s (user=%s), skipping", agent_id, user_id)
        return False


async def record_component_download(
    component_type: str,
    component_id: uuid.UUID,
    version_ref: str,
    agent_id: uuid.UUID,
    source: str,
    db: AsyncSession,
) -> None:
    """Record a component download (not deduplicated)."""
    db.add(
        ComponentDownloadRecord(
            component_type=component_type,
            component_id=component_id,
            version_ref=version_ref,
            agent_id=agent_id,
            source=source,
        )
    )
    await db.flush()


async def _update_agent_counts(agent_id: uuid.UUID, db: AsyncSession) -> None:
    """Recompute download_count for an agent's latest version."""
    total = (
        await db.scalar(select(func.count(AgentDownloadRecord.id)).where(AgentDownloadRecord.agent_id == agent_id)) or 0
    )
    agent = await db.get(Agent, agent_id)
    if agent and agent.latest_version:
        agent.latest_version.download_count = total


async def get_download_stats(agent_id: uuid.UUID, db: AsyncSession) -> dict:
    """Get download statistics for an agent."""
    from datetime import timedelta

    total = (
        await db.scalar(select(func.count(AgentDownloadRecord.id)).where(AgentDownloadRecord.agent_id == agent_id)) or 0
    )
    unique = (
        await db.scalar(
            select(func.count(func.distinct(AgentDownloadRecord.user_id))).where(
                AgentDownloadRecord.agent_id == agent_id,
                AgentDownloadRecord.user_id.isnot(None),
            )
        )
        or 0
    )

    # Recent 7-day downloads
    cutoff = datetime.now(UTC) - timedelta(days=7)
    recent_7d = (
        await db.scalar(
            select(func.count(AgentDownloadRecord.id)).where(
                AgentDownloadRecord.agent_id == agent_id,
                AgentDownloadRecord.installed_at >= cutoff,
            )
        )
        or 0
    )

    # Source breakdown
    source_rows = await db.execute(
        select(AgentDownloadRecord.source, func.count(AgentDownloadRecord.id).label("cnt"))
        .where(AgentDownloadRecord.agent_id == agent_id)
        .group_by(AgentDownloadRecord.source)
    )
    sources = {r.source: r.cnt for r in source_rows.all()}

    return {
        "total": total,
        "total_downloads": total,
        "unique_users": unique,
        "recent_7d": recent_7d,
        "sources": sources,
    }
