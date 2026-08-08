# SPDX-FileCopyrightText: 2026 Lokesh Selvam <lokeshselvam7025@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""Admin-minted invite links: create, list, revoke.

An invite authorizes account creation only — never membership, content, or an
elevated role. The plaintext token is returned exactly once at mint time; only
its SHA-256 lives in the database. The dynamic setting
``auth.invite_links_enabled`` gates minting AND redemption, so turning it off
kills every outstanding link at once.
"""

import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from urllib.parse import quote

from fastapi import Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import services.dynamic_settings as ds
from api.deps import get_db, require_role

# Reuse the exact same relative-only rule every other `next` consumer obeys —
# a divergent copy here would be an open-redirect waiting to happen.
from api.routes.auth import _is_safe_next
from models.invite import Invite
from models.user import User, UserRole
from services.security_events import EventType, SecurityEvent, Severity, emit_security_event

from ._router import router


class InviteCreateRequest(BaseModel):
    expires_in_days: int = Field(default=7, ge=1, le=365)
    max_uses: int | None = Field(default=None, ge=1, le=10000)
    next_path: str | None = Field(default=None, max_length=500)


class InviteResponse(BaseModel):
    id: uuid.UUID
    invited_by_username: str | None = None
    max_uses: int | None = None
    use_count: int
    next_path: str | None = None
    expires_at: datetime
    revoked_at: datetime | None = None
    created_at: datetime | None = None
    state: str
    model_config = ConfigDict(from_attributes=True)


class InviteCreatedResponse(InviteResponse):
    # Returned exactly once; the server stores only the hash.
    token: str
    url: str


def invite_state(invite: Invite, now: datetime) -> str:
    if invite.revoked_at is not None:
        return "revoked"
    expires = invite.expires_at
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=UTC)
    if expires <= now:
        return "expired"
    if invite.max_uses is not None and invite.use_count >= invite.max_uses:
        return "exhausted"
    return "active"


def _response(invite: Invite, username: str | None, now: datetime) -> InviteResponse:
    return InviteResponse(
        id=invite.id,
        invited_by_username=username,
        max_uses=invite.max_uses,
        use_count=invite.use_count,
        next_path=invite.next_path,
        expires_at=invite.expires_at,
        revoked_at=invite.revoked_at,
        created_at=invite.created_at,
        state=invite_state(invite, now),
    )


async def _emit_invite_event(event_type: EventType, invite: Invite, actor: User, detail: str) -> None:
    await emit_security_event(
        SecurityEvent(
            event_type=event_type,
            severity=Severity.INFO,
            outcome="success",
            actor_id=str(actor.id),
            actor_email=actor.email,
            actor_role=actor.role.value,
            target_id=str(invite.id),
            target_type="invite",
            detail=detail,
        )
    )


@router.post("/invites", response_model=InviteCreatedResponse, status_code=201)
async def create_invite(
    req: InviteCreateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin)),
):
    """Mint an invite link. The token in the response is shown exactly once."""
    if not await ds.get_bool("auth.invite_links_enabled"):
        raise HTTPException(
            status_code=403,
            detail="Invite links are disabled. Enable auth.invite_links_enabled in admin settings first.",
        )

    next_path = (req.next_path or "").strip() or None
    if next_path and not _is_safe_next(next_path):
        raise HTTPException(status_code=422, detail="next_path must be a relative path starting with /")

    token = secrets.token_urlsafe(32)
    now = datetime.now(UTC)
    invite = Invite(
        token_hash=hashlib.sha256(token.encode()).hexdigest(),
        invited_by=current_user.id,
        max_uses=req.max_uses,
        next_path=next_path,
        expires_at=now + timedelta(days=req.expires_in_days),
    )
    db.add(invite)
    await db.commit()

    frontend = str(ds.get_sync("deployment.frontend_url", "http://localhost:3000")).rstrip("/")
    url = f"{frontend}/register?invite={token}"
    if next_path:
        url += f"&next={quote(next_path, safe='/')}"

    await _emit_invite_event(
        EventType.INVITE_CREATED,
        invite,
        current_user,
        f"Invite minted (expires {invite.expires_at.date()}, max_uses={req.max_uses or 'unlimited'})",
    )
    base = _response(invite, current_user.username, now)
    return InviteCreatedResponse(**base.model_dump(), token=token, url=url)


@router.get("/invites", response_model=list[InviteResponse])
async def list_invites(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin)),
):
    del current_user
    rows = (
        await db.execute(
            select(Invite, User.username)
            .outerjoin(User, User.id == Invite.invited_by)
            .order_by(Invite.created_at.desc())
        )
    ).all()
    now = datetime.now(UTC)
    return [_response(invite, username, now) for invite, username in rows]


@router.post("/invites/{invite_id}/revoke", response_model=InviteResponse)
async def revoke_invite(
    invite_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin)),
):
    """Revoke an invite. Idempotent; already-created accounts are unaffected."""
    invite = await db.get(Invite, invite_id)
    if not invite:
        raise HTTPException(status_code=404, detail="Invite not found")
    if invite.revoked_at is None:
        invite.revoked_at = datetime.now(UTC)
        await db.commit()
        await _emit_invite_event(EventType.INVITE_REVOKED, invite, current_user, "Invite revoked")
    inviter = await db.get(User, invite.invited_by) if invite.invited_by else None
    return _response(invite, inviter.username if inviter else None, datetime.now(UTC))
