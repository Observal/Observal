# SPDX-FileCopyrightText: 2026 Aryan Iyappan <aryaniyappan2006@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Teammate invite routes.

Admins create single-use, time-limited invite tokens (optionally pinned to
an email address). The raw token is returned exactly once; only its SHA-256
hash is stored. Anyone holding the link can preview it (lookup) and accept
it (public, password-auth deployments only), which creates an account in
the inviting org with the preassigned role and logs the user in.

There is no SMTP integration: for channel=email the admin copies the
generated link and sends it through their own channel; the invite is simply
pinned to that address at acceptance time.
"""

import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from loguru import logger as optic
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import ROLE_HIERARCHY, get_db, require_password_auth, require_role
from api.ratelimit import limiter
from models.invite import Invite, InviteChannel
from models.organization import Organization
from models.user import User, UserRole
from schemas.auth import UserResponse
from schemas.invite import (
    InviteAcceptRequest,
    InviteAcceptResponse,
    InviteCreateRequest,
    InviteCreateResponse,
    InviteLookupResponse,
    InviteResponse,
)
from services.events import InviteAccepted, InviteSent, UserCreated, bus
from services.security_events import EventType, SecurityEvent, Severity, emit_security_event
from services.username_generator import generate_unique_username

router = APIRouter(prefix="/api/v1/invites", tags=["invites"])

INVITE_TTL_DAYS = 7


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


async def _get_invite_by_token(db: AsyncSession, token: str) -> Invite | None:
    result = await db.execute(select(Invite).where(Invite.token_hash == _hash_token(token)))
    return result.scalar_one_or_none()


# ── Admin: create / list / revoke ────────────────────────────────────


@router.post("", response_model=InviteCreateResponse, dependencies=[Depends(require_password_auth)])
async def create_invite(
    req: InviteCreateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin)),
):
    optic.debug("invite create requested")
    try:
        role = UserRole(req.role)
    except ValueError:
        raise HTTPException(status_code=422, detail=f"Invalid role. Must be one of: {[r.value for r in UserRole]}")

    if ROLE_HIERARCHY.get(role, 999) < ROLE_HIERARCHY[current_user.role]:
        raise HTTPException(status_code=403, detail="Cannot assign a role higher than your own")

    if not current_user.org_id:
        raise HTTPException(status_code=400, detail="Your account has no organization")

    if req.email:
        existing = await db.scalar(select(User.id).where(User.email == req.email))
        if existing:
            raise HTTPException(status_code=409, detail="A user with this email already exists")

        now = datetime.now(UTC)
        pending = await db.execute(
            select(Invite).where(
                Invite.org_id == current_user.org_id,
                Invite.email == req.email,
                Invite.revoked.is_(False),
                Invite.accepted_at.is_(None),
                Invite.expires_at > now,
            )
        )
        if pending.scalars().first():
            raise HTTPException(status_code=409, detail="A pending invite for this email already exists")

    token = secrets.token_urlsafe(32)
    invite = Invite(
        org_id=current_user.org_id,
        email=req.email,
        role=role,
        channel=InviteChannel.email if req.email else InviteChannel.link,
        token_hash=_hash_token(token),
        invited_by=current_user.id,
        expires_at=datetime.now(UTC) + timedelta(days=INVITE_TTL_DAYS),
    )
    db.add(invite)
    await db.commit()
    await db.refresh(invite)

    await bus.emit(
        InviteSent(
            invite_id=str(invite.id),
            org_id=str(invite.org_id),
            channel=invite.channel.value,
            invited_by=str(current_user.id),
        )
    )
    await emit_security_event(
        SecurityEvent(
            event_type=EventType.INVITE_CREATED,
            severity=Severity.INFO,
            outcome="success",
            actor_id=str(current_user.id),
            actor_email=current_user.email,
            actor_role=current_user.role.value,
            target_id=str(invite.id),
            target_type="invite",
            detail=f"Invite created ({invite.channel.value}) with role {role.value}",
        )
    )

    from api.routes.device_auth import _resolve_frontend_url

    invite_url = f"{_resolve_frontend_url(request)}/invite/{token}"
    return InviteCreateResponse(
        id=invite.id,
        email=invite.email,
        role=invite.role.value,
        channel=invite.channel.value,
        status=invite.status,
        created_at=invite.created_at,
        expires_at=invite.expires_at,
        accepted_at=invite.accepted_at,
        token=token,
        invite_url=invite_url,
    )


@router.get("", response_model=list[InviteResponse])
async def list_invites(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin)),
):
    optic.debug("invite list requested")
    stmt = select(Invite).order_by(Invite.created_at.desc())
    if current_user.org_id is not None:
        stmt = stmt.where(Invite.org_id == current_user.org_id)
    result = await db.execute(stmt)
    return [InviteResponse.model_validate(i) for i in result.scalars().all()]


@router.delete("/{invite_id}", status_code=204)
async def revoke_invite(
    invite_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin)),
):
    optic.debug("invite revoke requested")
    stmt = select(Invite).where(Invite.id == invite_id)
    if current_user.org_id is not None:
        stmt = stmt.where(Invite.org_id == current_user.org_id)
    result = await db.execute(stmt)
    invite = result.scalar_one_or_none()
    if not invite:
        raise HTTPException(status_code=404, detail="Invite not found")
    if invite.accepted_at is not None:
        raise HTTPException(status_code=400, detail="Invite has already been accepted")

    invite.revoked = True
    await db.commit()


# ── Public: lookup / accept ──────────────────────────────────────────


@router.get("/lookup/{token}", response_model=InviteLookupResponse)
@limiter.limit("20/minute")
async def lookup_invite(token: str, request: Request, db: AsyncSession = Depends(get_db)):
    """Public preview of an invite for the acceptance page. Never 404s on a
    bad token (to keep responses uniform); returns valid=false instead."""
    optic.debug("invite lookup requested")
    invite = await _get_invite_by_token(db, token)
    if not invite:
        return InviteLookupResponse(valid=False, reason="not_found")

    status = invite.status
    if status != "pending":
        return InviteLookupResponse(valid=False, reason=status)

    org_name = await db.scalar(select(Organization.name).where(Organization.id == invite.org_id))
    return InviteLookupResponse(
        valid=True,
        org_name=org_name,
        email=invite.email,
        role=invite.role.value,
        expires_at=invite.expires_at,
    )


@router.post("/accept", response_model=InviteAcceptResponse, dependencies=[Depends(require_password_auth)])
@limiter.limit("5/minute")
async def accept_invite(req: InviteAcceptRequest, request: Request, db: AsyncSession = Depends(get_db)):
    """Accept an invite: create the account in the inviting org and log in."""
    optic.debug("invite accept requested")
    invite = await _get_invite_by_token(db, req.token)
    if not invite:
        raise HTTPException(status_code=404, detail="Invite not found")

    status = invite.status
    if status == "revoked":
        raise HTTPException(status_code=410, detail="This invite has been revoked")
    if status == "accepted":
        raise HTTPException(status_code=410, detail="This invite has already been used")
    if status == "expired":
        raise HTTPException(status_code=410, detail="This invite has expired")

    if invite.email:
        if req.email and req.email != invite.email:
            raise HTTPException(status_code=400, detail="This invite is for a different email address")
        email = invite.email
    else:
        if not req.email:
            raise HTTPException(status_code=422, detail="Email is required for this invite")
        email = req.email

    existing = await db.scalar(select(User.id).where(User.email == email))
    if existing:
        raise HTTPException(status_code=409, detail="A user with this email already exists")

    from api.routes.auth import _issue_tokens, _validate_password_strength

    _validate_password_strength(req.password)

    username = req.username or await generate_unique_username(email, db)
    user = User(
        email=email,
        username=username,
        name=req.name,
        role=invite.role,
        org_id=invite.org_id,
        auth_provider="local",
    )
    user.set_password(req.password)
    db.add(user)
    try:
        await db.flush()
        invite.accepted_at = datetime.now(UTC)
        invite.accepted_by = user.id
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="Email or username already exists")
    await db.refresh(user)

    org_id = str(user.org_id) if user.org_id else None
    # utm_source is forced to "invite" so the GTM engine attributes this
    # signup to the invite loop regardless of stored first-touch UTMs.
    await bus.emit(
        UserCreated(
            user_id=str(user.id),
            email=user.email,
            role=user.role.value,
            name=user.name,
            org_id=org_id,
            auth_provider="local",
            utm_source="invite",
        )
    )
    await bus.emit(
        InviteAccepted(
            invite_id=str(invite.id),
            org_id=org_id,
            user_id=str(user.id),
        )
    )
    await emit_security_event(
        SecurityEvent(
            event_type=EventType.REGISTRATION,
            severity=Severity.INFO,
            outcome="success",
            actor_id=str(user.id),
            actor_email=user.email,
            actor_role=user.role.value,
            target_id=str(invite.id),
            target_type="invite",
            detail=f"User {user.email} signed up via invite",
        )
    )

    access_token, refresh_token, expires_in = await _issue_tokens(user)
    return InviteAcceptResponse(
        user=UserResponse.model_validate(user),
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=expires_in,
    )
