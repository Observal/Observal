"""Demo account seeding and lifecycle management.

Seeds demo accounts on first startup when no real users exist and DEMO_*
env vars are configured.  Cleans them up automatically when real users
are created at the corresponding tier.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from sqlalchemy import delete, func, select

from config import settings

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession
from models.user import User, UserRole
from services.events import UserCreated, bus

logger = logging.getLogger("observal.demo")

# (env-var prefix, role) — order matters for seeding log readability
DEMO_TIERS: list[tuple[str, UserRole]] = [
    ("DEMO_SUPER_ADMIN", UserRole.super_admin),
    ("DEMO_ADMIN", UserRole.admin),
    ("DEMO_REVIEWER", UserRole.reviewer),
    ("DEMO_USER", UserRole.user),
]


async def seed_demo_accounts(db: AsyncSession) -> int:
    """Create demo accounts if no real users exist and env vars are set.

    Returns the number of accounts created.  Idempotent — skips accounts
    that already exist.
    """
    # Bail out if ANY real (non-demo) user exists
    real_count = await db.scalar(select(func.count()).select_from(User).where(User.is_demo.is_(False)))
    if real_count and real_count > 0:
        return 0

    created = 0
    for prefix, role in DEMO_TIERS:
        email = getattr(settings, f"{prefix}_EMAIL", None)
        password = getattr(settings, f"{prefix}_PASSWORD", None)
        if not email or not password:
            continue
        email = email.strip().lower()

        # Idempotent: skip if already exists
        exists = await db.scalar(select(func.count()).select_from(User).where(User.email == email))
        if exists:
            continue

        user = User(
            email=email,
            name=f"Demo {role.value.replace('_', ' ').title()}",
            role=role,
            is_demo=True,
        )
        user.set_password(password)
        db.add(user)
        created += 1

    if created:
        await db.commit()
        logger.warning(
            "Created %d demo account(s) — create a real super_admin to remove them",
            created,
        )

    return created


async def cleanup_demo_accounts(db: AsyncSession, new_role: UserRole) -> int:
    """Delete demo accounts when a real user at the given tier is created.

    - Real super_admin → delete ALL demo accounts
    - Real admin/reviewer/user → delete the demo account for that role only

    Returns the number of deleted accounts.
    """
    if new_role == UserRole.super_admin:
        stmt = delete(User).where(User.is_demo.is_(True))
    else:
        stmt = delete(User).where(User.is_demo.is_(True), User.role == new_role)

    result = await db.execute(stmt)
    deleted: int = result.rowcount  # type: ignore[assignment]
    if deleted:
        await db.commit()
        logger.info(
            "Cleaned up %d demo account(s) after real %s was created",
            deleted,
            new_role.value,
        )
    return deleted


# ── Event handler ────────────────────────────────────────


@bus.on(UserCreated)
async def _on_user_created(event: UserCreated) -> None:
    """Auto-cleanup demo accounts when a real user is created."""
    if event.is_demo:
        return  # Don't trigger cleanup for demo accounts themselves

    from database import async_session

    async with async_session() as db:
        await cleanup_demo_accounts(db, UserRole(event.role))
