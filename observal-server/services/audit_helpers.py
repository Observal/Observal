"""Convenience wrapper for emitting audit events.

Reduces each call site to a single line::

    await audit(current_user, "mcp.submit", "mcp", str(listing.id), listing.name)
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from services.events import AuditableAction, bus

if TYPE_CHECKING:
    from models.user import User


async def audit(
    user: User | None,
    action: str,
    resource_type: str = "",
    resource_id: str = "",
    resource_name: str = "",
    detail: str = "",
) -> None:
    """Emit an ``AuditableAction`` event for the given user and action.

    No-ops when *user* is ``None`` (anonymous / unauthenticated requests).
    """
    if user is None:
        return
    await bus.emit(
        AuditableAction(
            actor_id=str(user.id),
            actor_email=user.email or "",
            actor_role=user.role.value if hasattr(user.role, "value") else str(user.role),
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            resource_name=resource_name,
            detail=detail,
        )
    )
