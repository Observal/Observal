# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: Apache-2.0

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from api.deps import get_db, require_role
from models.team import Team, TeamJoinRequestStatus, TeamMembership, TeamMembershipRequest, TeamRole
from models.user import User, UserRole
from schemas.team import (
    TeamCreateRequest,
    TeamJoinDecisionRequest,
    TeamJoinRequestCreate,
    TeamJoinRequestResponse,
    TeamMemberResponse,
    TeamMemberUpsertRequest,
    TeamResponse,
    TeamUpdateRequest,
    TeamVisibilityUpdateRequest,
)
from services.inbox import sources as inbox_sources
from services.security_events import EventType, SecurityEvent, Severity, emit_security_event
from services.teamspace import (
    REVIEWING_TEAM_ROLES,
    count_owners,
    is_admin,
    is_global_reviewer,
    reserve_handle,
    slugify_handle,
    team_membership,
    team_visible_to,
)

router = APIRouter(prefix="/api/v1/teams", tags=["teams"])

_PERSONAL_TEAM_DESCRIPTION = "Your private teamspace for drafts and personal publishing."


def _role_value(role) -> str | None:
    if role is None:
        return None
    return role.value if hasattr(role, "value") else str(role)


async def _load_team(db: AsyncSession, team_id: uuid.UUID) -> Team:
    team = await db.get(Team, team_id)
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")
    return team


async def _load_visible_team(db: AsyncSession, team_id: uuid.UUID, user: User) -> Team:
    """Load a team the caller may see, answering 404 (never 403) when hidden.

    A private teamspace is indistinguishable from a nonexistent one for plain
    users outside it; members and global reviewers/admins see it normally.
    """
    team = await _load_team(db, team_id)
    membership = await team_membership(db, team.id, user.id)
    if not team_visible_to(team, membership, user):
        raise HTTPException(status_code=404, detail="Team not found")
    return team


async def _require_owner_or_admin(db: AsyncSession, team_id: uuid.UUID, user: User) -> Team:
    team = await _load_team(db, team_id)
    if is_admin(user):
        return team
    membership = await team_membership(db, team_id, user.id)
    if not membership or membership.role != TeamRole.owner:
        # A non-member of a PRIVATE team must not learn it exists: answer 404,
        # exactly like a missing team, rather than a 403 that confirms it. A
        # public team is openly listed, so 403 there leaks nothing.
        if not team_visible_to(team, membership, user):
            raise HTTPException(status_code=404, detail="Team not found")
        raise HTTPException(status_code=403, detail="Only team owners can manage this team")
    return team


async def _resolve_member(db: AsyncSession, req: TeamMemberUpsertRequest) -> User:
    if req.user_id:
        stmt = select(User).where(User.id == req.user_id)
    elif req.email:
        stmt = select(User).where(User.email == req.email.strip().lower())
    elif req.username:
        stmt = select(User).where(User.username == req.username.strip().lstrip("@"))
    else:
        raise HTTPException(status_code=422, detail="Provide email, username, or user_id")
    target = (await db.execute(stmt)).scalar_one_or_none()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    return target


@router.get("", response_model=list[TeamResponse])
async def my_teams(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.user)),
):
    rows = (
        await db.execute(
            select(Team, TeamMembership.role)
            .join(TeamMembership, TeamMembership.team_id == Team.id)
            .where(TeamMembership.user_id == current_user.id)
            .order_by(Team.name)
        )
    ).all()
    return [
        TeamResponse(
            id=team.id,
            name=team.name,
            handle=team.handle,
            description=team.description,
            visibility=team.visibility,
            is_personal=team.is_personal,
            role=_role_value(role),
            created_at=team.created_at,
        )
        for team, role in rows
    ]


@router.get("/all", response_model=list[TeamResponse])
async def all_teams(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.user)),
):
    member_counts = (
        select(TeamMembership.team_id, func.count(TeamMembership.id).label("count"))
        .group_by(TeamMembership.team_id)
        .subquery()
    )
    my_roles = (
        select(TeamMembership.team_id, TeamMembership.role).where(TeamMembership.user_id == current_user.id).subquery()
    )
    stmt = (
        select(Team, func.coalesce(member_counts.c.count, 0), my_roles.c.role)
        .outerjoin(member_counts, member_counts.c.team_id == Team.id)
        .outerjoin(my_roles, my_roles.c.team_id == Team.id)
        .order_by(Team.name)
    )
    # Private teamspaces are hidden from plain users who are not members;
    # global reviewers, admins, and super_admins see everything.
    if not is_global_reviewer(current_user):
        stmt = stmt.where(or_(Team.is_private == False, my_roles.c.role.is_not(None)))  # noqa: E712
    rows = (await db.execute(stmt)).all()
    return [
        TeamResponse(
            id=team.id,
            name=team.name,
            handle=team.handle,
            description=team.description,
            visibility=team.visibility,
            is_personal=team.is_personal,
            role=_role_value(role),
            member_count=int(count) if count is not None else 0,
            created_at=team.created_at,
        )
        for team, count, role in rows
    ]


@router.get("/by-handle/{handle}", response_model=TeamResponse)
async def team_by_handle(
    handle: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.user)),
):
    """Resolve a teamspace by its canonical handle for /teamspaces/{handle} pages.

    Public teamspaces resolve for any signed-in user — they are already
    enumerable through GET /teams/all. Private ones resolve only for members
    and global reviewers/admins and otherwise answer 404, exactly like a
    handle that does not exist. Anonymous callers get the standard 401 sign-in
    challenge from require_role, which the web app turns into a login redirect
    that returns to the requested page.
    """
    normalized = handle.strip().lstrip("@").lower()
    team = (await db.execute(select(Team).where(Team.handle == normalized))).scalar_one_or_none()
    if not team:
        raise HTTPException(status_code=404, detail="Teamspace not found")
    membership = await team_membership(db, team.id, current_user.id)
    if not team_visible_to(team, membership, current_user):
        # A hidden teamspace answers exactly like a missing one.
        raise HTTPException(status_code=404, detail="Teamspace not found")
    if is_admin(current_user):
        role = _role_value(TeamRole.owner)
    else:
        role = _role_value(membership.role) if membership else None
    member_count = await db.scalar(select(func.count(TeamMembership.id)).where(TeamMembership.team_id == team.id))
    return TeamResponse(
        id=team.id,
        name=team.name,
        handle=team.handle,
        description=team.description,
        visibility=team.visibility,
        is_personal=team.is_personal,
        role=role,
        member_count=int(member_count or 0),
        created_at=team.created_at,
    )


@router.get("/{team_id}", response_model=TeamResponse)
async def team_detail(
    team_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.user)),
):
    team = await _load_visible_team(db, team_id, current_user)
    role = None
    if not is_admin(current_user):
        membership = await team_membership(db, team.id, current_user.id)
        role = _role_value(membership.role) if membership else None
    else:
        role = _role_value(TeamRole.owner)
    return TeamResponse(
        id=team.id,
        name=team.name,
        handle=team.handle,
        description=team.description,
        visibility=team.visibility,
        is_personal=team.is_personal,
        role=role,
        created_at=team.created_at,
    )


@router.post("", response_model=TeamResponse)
async def create_team(
    req: TeamCreateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.user)),
):
    """Create a teamspace. Any signed-in user may; the creator becomes its owner."""
    raw_handle = req.handle or req.name
    try:
        handle = await reserve_handle(db, raw_handle)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    team = Team(
        name=req.name.strip(),
        handle=handle,
        description=req.description,
        is_private=req.visibility == "private",
        created_by=current_user.id,
    )
    db.add(team)
    try:
        await db.flush()
        db.add(TeamMembership(team_id=team.id, user_id=current_user.id, role=TeamRole.owner))
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="Team handle already exists")
    await db.refresh(team)
    return TeamResponse(
        id=team.id,
        name=team.name,
        handle=team.handle,
        description=team.description,
        visibility=team.visibility,
        is_personal=team.is_personal,
        role=_role_value(TeamRole.owner),
        member_count=1,
        created_at=team.created_at,
    )


async def _personal_team_response(db: AsyncSession, team: Team, user: User) -> TeamResponse:
    membership = await team_membership(db, team.id, user.id)
    member_count = await db.scalar(select(func.count(TeamMembership.id)).where(TeamMembership.team_id == team.id))
    return TeamResponse(
        id=team.id,
        name=team.name,
        handle=team.handle,
        description=team.description,
        visibility=team.visibility,
        is_personal=True,
        role=_role_value(membership.role) if membership else None,
        member_count=int(member_count or 0),
        created_at=team.created_at,
    )


@router.post("/claim-personal", response_model=TeamResponse)
async def claim_personal_teamspace(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.user)),
):
    """Create or return the caller's one personal private teamspace."""
    personal = (
        await db.execute(select(Team).where(Team.created_by == current_user.id, Team.is_personal.is_(True)))
    ).scalar_one_or_none()
    if personal is not None:
        return await _personal_team_response(db, personal, current_user)

    display = (current_user.name or current_user.username or "My").strip()
    base = slugify_handle(f"{current_user.username or 'personal'}-team")
    candidates = [base] + [slugify_handle(f"{base[:29].rstrip('-')}-{i}") for i in range(1, 6)]

    for candidate in candidates:
        existing = (await db.execute(select(Team).where(Team.handle == candidate))).scalar_one_or_none()
        if existing is not None:
            membership = await team_membership(db, existing.id, current_user.id)
            legacy_personal = (
                existing.created_by == current_user.id
                and existing.is_private
                and existing.description == _PERSONAL_TEAM_DESCRIPTION
            )
            if membership is not None and membership.role == TeamRole.owner and legacy_personal:
                existing.is_personal = True
                try:
                    await db.commit()
                except IntegrityError:
                    await db.rollback()
                    personal = (
                        await db.execute(
                            select(Team).where(
                                Team.created_by == current_user.id,
                                Team.is_personal.is_(True),
                            )
                        )
                    ).scalar_one_or_none()
                    if personal is not None:
                        return await _personal_team_response(db, personal, current_user)
                    raise
                return await _personal_team_response(db, existing, current_user)
            continue

        try:
            handle = await reserve_handle(db, candidate)
        except ValueError:
            continue
        team = Team(
            name=f"{display}'s Teamspace",
            handle=handle,
            description=_PERSONAL_TEAM_DESCRIPTION,
            is_private=True,
            is_personal=True,
            created_by=current_user.id,
        )
        db.add(team)
        try:
            await db.flush()
            db.add(TeamMembership(team_id=team.id, user_id=current_user.id, role=TeamRole.owner))
            await db.commit()
        except IntegrityError:
            await db.rollback()
            personal = (
                await db.execute(select(Team).where(Team.created_by == current_user.id, Team.is_personal.is_(True)))
            ).scalar_one_or_none()
            if personal is not None:
                return await _personal_team_response(db, personal, current_user)
            continue
        await db.refresh(team)
        return await _personal_team_response(db, team, current_user)

    raise HTTPException(status_code=409, detail="Could not find a free handle for your personal teamspace")


@router.put("/{team_id}", response_model=TeamResponse)
async def update_team(
    team_id: uuid.UUID,
    req: TeamUpdateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.user)),
):
    team = await _require_owner_or_admin(db, team_id, current_user)
    if req.name is not None:
        team.name = req.name.strip()
    if req.description is not None:
        team.description = req.description
    await db.commit()
    await db.refresh(team)
    return TeamResponse(
        id=team.id,
        name=team.name,
        handle=team.handle,
        description=team.description,
        visibility=team.visibility,
        is_personal=team.is_personal,
        role=_role_value(TeamRole.owner),
        created_at=team.created_at,
    )


@router.patch("/{team_id}/visibility", response_model=TeamResponse)
async def update_team_visibility(
    team_id: uuid.UUID,
    req: TeamVisibilityUpdateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.user)),
):
    """Flip a teamspace between public and private, GitHub-style.

    Team owners and team reviewers hold this control (plus deployment admins).
    Going private hides the teamspace from plain non-member users everywhere —
    discovery, by-handle resolution, and join requests — while members and
    global reviewers/admins keep seeing it. Listings keep their own visibility:
    a public listing published from the teamspace stays in the public catalog.
    """
    team = await _load_team(db, team_id)
    membership = await team_membership(db, team.id, current_user.id)
    allowed = is_admin(current_user) or (membership is not None and membership.role in REVIEWING_TEAM_ROLES)
    if not allowed:
        # Members and outsiders both land here; a plain non-member of a private
        # team gets 404 elsewhere, so keep this 403 for members only.
        if membership is None and not team_visible_to(team, membership, current_user):
            raise HTTPException(status_code=404, detail="Team not found")
        raise HTTPException(status_code=403, detail="Only team owners and reviewers can change visibility")

    changed = team.is_private != (req.visibility == "private")
    team.is_private = req.visibility == "private"
    await db.commit()
    await db.refresh(team)
    if changed:
        await emit_security_event(
            SecurityEvent(
                event_type=EventType.TEAM_VISIBILITY_CHANGED,
                severity=Severity.INFO,
                outcome="success",
                actor_id=str(current_user.id),
                actor_email=current_user.email,
                actor_role=current_user.role.value,
                target_id=str(team.id),
                target_type="team",
                detail=f"Teamspace '{team.handle}' is now {team.visibility}",
            )
        )
    role = (
        _role_value(TeamRole.owner) if is_admin(current_user) else _role_value(membership.role) if membership else None
    )
    return TeamResponse(
        id=team.id,
        name=team.name,
        handle=team.handle,
        description=team.description,
        visibility=team.visibility,
        is_personal=team.is_personal,
        role=role,
        created_at=team.created_at,
    )


async def _team_owned_listing_counts(db: AsyncSession, team_id: uuid.UUID) -> dict[str, int]:
    """Count everything published under a teamspace, by kind.

    The team_id foreign keys are ON DELETE RESTRICT as of migration 019, so the
    database refuses the delete on its own. This count exists only to answer with a
    message naming what is in the way instead of surfacing an integrity error, and
    it is deliberately not the enforcement: counting and then deleting is racy, and
    a publish landing in between is caught by the constraint rather than here.
    """
    from models.agent import Agent
    from models.component_source import ComponentSource
    from models.hook import HookListing
    from models.mcp import McpListing
    from models.prompt import PromptListing
    from models.sandbox import SandboxListing
    from models.skill import SkillListing

    # (singular, plural) so a count of one does not read "1 skills".
    labels = {
        Agent: ("agent", "agents"),
        McpListing: ("MCP server", "MCP servers"),
        SkillListing: ("skill", "skills"),
        HookListing: ("hook", "hooks"),
        PromptListing: ("prompt", "prompts"),
        SandboxListing: ("sandbox", "sandboxes"),
        ComponentSource: ("component source", "component sources"),
    }
    counts: dict[str, int] = {}
    for model, (singular, plural) in labels.items():
        # Soft-deleted agents count too. They are restorable and still carry the
        # teamspace's namespace, so freeing the handle while one exists lets a new
        # team claim it and inherit that agent on restore.
        total = await db.scalar(select(func.count(model.id)).where(model.team_id == team_id))
        if total:
            counts[singular if total == 1 else plural] = total
    return counts


@router.delete("/{team_id}", status_code=204)
async def delete_team(
    team_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.user)),
):
    team = await _require_owner_or_admin(db, team_id, current_user)

    # Refuse while the teamspace still owns listings. ON DELETE SET NULL would
    # otherwise leave every one of them with is_private=True and team_id=NULL:
    # the membership check can no longer match anybody, so each listing silently
    # collapses to creator-only access while still reporting visibility "team",
    # and no member other than its original submitter can reach it again. The
    # handle also becomes free to claim, which would hand those listings'
    # namespace to whoever registers it next. Make the owner deal with the
    # listings first rather than destroying access as a side effect.
    owned = await _team_owned_listing_counts(db, team.id)
    if owned:
        # Public listings block too. Changing visibility does not clear team_id, and
        # deleting the team frees the handle for anyone to claim, which would hand a
        # new owner the namespace those listings still carry. Only transferring or
        # deleting them actually detaches them, so the message says exactly that.
        detail = ", ".join(f"{count} {label}" for label, count in sorted(owned.items()))
        raise HTTPException(
            status_code=409,
            detail=(
                f"Teamspace '{team.handle}' still owns {detail}. Transfer each listing to a user with "
                "POST /api/v1/{entity_type}/{id}/transfer-ownership, which moves it out of the "
                "teamspace, or delete it. Deleting the teamspace first would strip its members' access and "
                "leave the handle claimable by someone else."
            ),
        )

    await db.delete(team)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(status_code=409, detail="Teamspace still owns registry items") from exc


@router.get("/{team_id}/members", response_model=list[TeamMemberResponse])
async def list_team_members(
    team_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.user)),
):
    team = await _load_team(db, team_id)
    # Members and admins can see the roster.
    if not is_admin(current_user):
        membership = await team_membership(db, team.id, current_user.id)
        if not membership:
            # 404 for a private team the caller cannot see (no existence leak);
            # 403 for a public one, whose existence is already open.
            if not team_visible_to(team, membership, current_user):
                raise HTTPException(status_code=404, detail="Team not found")
            raise HTTPException(status_code=403, detail="Only team members can view the roster")
    rows = (
        await db.execute(
            select(User.id, User.email, User.username, User.name, TeamMembership.role)
            .join(TeamMembership, TeamMembership.user_id == User.id)
            .where(TeamMembership.team_id == team_id)
            .order_by(User.email)
        )
    ).all()
    return [
        TeamMemberResponse(
            id=row.id,
            email=row.email,
            username=row.username,
            name=row.name,
            role=_role_value(row.role),
        )
        for row in rows
    ]


@router.post("/{team_id}/members", response_model=TeamMemberResponse)
async def upsert_team_member(
    team_id: uuid.UUID,
    req: TeamMemberUpsertRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.user)),
):
    team = await _require_owner_or_admin(db, team_id, current_user)
    target = await _resolve_member(db, req)
    membership = await team_membership(db, team.id, target.id)
    if membership:
        # Demoting the last owner is not allowed.
        if (
            membership.role == TeamRole.owner
            and req.role != TeamRole.owner
            and await count_owners(db, team.id, for_update=True) <= 1
        ):
            raise HTTPException(status_code=409, detail="A team must have at least one owner")
        membership.role = req.role
    else:
        db.add(TeamMembership(team_id=team.id, user_id=target.id, role=req.role))
    await db.commit()
    return TeamMemberResponse(
        id=target.id,
        email=target.email,
        username=target.username,
        name=target.name,
        role=_role_value(req.role),
    )


@router.delete("/{team_id}/members/{user_id}", status_code=204)
async def remove_team_member(
    team_id: uuid.UUID,
    user_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.user)),
):
    team = await _require_owner_or_admin(db, team_id, current_user)
    membership = await team_membership(db, team.id, user_id)
    if not membership:
        raise HTTPException(status_code=404, detail="Membership not found")
    if membership.role == TeamRole.owner and await count_owners(db, team.id, for_update=True) <= 1:
        raise HTTPException(status_code=409, detail="A team must have at least one owner")
    await db.delete(membership)
    await db.commit()


@router.post("/{team_id}/leave", status_code=204)
async def leave_team(
    team_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.user)),
):
    team = await _load_team(db, team_id)
    membership = await team_membership(db, team.id, current_user.id)
    if not membership:
        raise HTTPException(status_code=404, detail="You are not a member of this team")
    if membership.role == TeamRole.owner and await count_owners(db, team.id, for_update=True) <= 1:
        raise HTTPException(status_code=409, detail="A team must have at least one owner; transfer ownership first")
    await db.delete(membership)
    await db.commit()


# ── Membership join requests ─────────────────────────────────────────
#
# A shared /teamspaces/{handle} link never grants access. It leads here: the
# recipient explicitly requests member access, owners (or admins) approve or
# reject from the teamspace's Join requests tab, and only the approval writes a
# membership row. The request row itself is the audit record — requester,
# reviewer, decision, reason, and timestamps.


def _join_request_response(
    row: TeamMembershipRequest,
    requester: User | None = None,
    decided_by_username: str | None = None,
) -> TeamJoinRequestResponse:
    return TeamJoinRequestResponse(
        id=row.id,
        team_id=row.team_id,
        user_id=row.user_id,
        email=requester.email if requester else None,
        username=requester.username if requester else None,
        name=requester.name if requester else None,
        status=row.status.value,
        message=row.message,
        decided_by=row.decided_by,
        decided_by_username=decided_by_username,
        decided_at=row.decided_at,
        decision_reason=row.decision_reason,
        created_at=row.created_at,
    )


async def _load_join_request(
    db: AsyncSession, team_id: uuid.UUID, request_id: uuid.UUID, *, for_update: bool = False
) -> TeamMembershipRequest:
    stmt = select(TeamMembershipRequest).where(
        TeamMembershipRequest.id == request_id,
        TeamMembershipRequest.team_id == team_id,
    )
    if for_update:
        # A decision reads status, then writes it and (on approval) a membership
        # row. Without the row lock, a concurrent approve+reject/cancel both pass
        # the in-memory `status == pending` guard and the later commit overwrites
        # the earlier one, leaving a member whose audit row says rejected or a
        # duplicate-membership constraint failure. Serialize the decision.
        stmt = stmt.with_for_update()
    row = (await db.execute(stmt)).scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Join request not found")
    return row


async def _emit_join_event(event_type: EventType, team: Team, actor: User, detail: str) -> None:
    await emit_security_event(
        SecurityEvent(
            event_type=event_type,
            severity=Severity.INFO,
            outcome="success",
            actor_id=str(actor.id),
            actor_email=actor.email,
            actor_role=actor.role.value,
            target_id=str(team.id),
            target_type="team",
            detail=detail,
        )
    )


@router.post("/{team_id}/join-requests", response_model=TeamJoinRequestResponse, status_code=201)
async def create_join_request(
    team_id: uuid.UUID,
    req: TeamJoinRequestCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.user)),
):
    """Ask for member access to a teamspace. Owners decide; the link never does."""
    # A private teamspace cannot be requested by someone who cannot see it.
    team = await _load_visible_team(db, team_id, current_user)
    membership = await team_membership(db, team.id, current_user.id)
    if membership:
        raise HTTPException(status_code=409, detail="You are already a member of this teamspace")

    message = (req.message or "").strip() or None
    row = TeamMembershipRequest(team_id=team.id, user_id=current_user.id, message=message)
    try:
        # SAVEPOINT so the partial-unique collision (one pending request per
        # user per team) can be answered without poisoning the transaction the
        # inbox delivery below still needs.
        async with db.begin_nested():
            db.add(row)
            await db.flush()
    except IntegrityError:
        raise HTTPException(status_code=409, detail="You already have a pending request for this teamspace") from None

    await inbox_sources.on_team_join_requested(db, team, requester_id=current_user.id, message=message)
    await db.commit()
    await _emit_join_event(EventType.TEAM_JOIN_REQUESTED, team, current_user, f"Requested to join '{team.handle}'")
    return _join_request_response(row, current_user)


@router.get("/{team_id}/join-requests/mine", response_model=list[TeamJoinRequestResponse])
async def my_join_requests(
    team_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.user)),
):
    """The caller's own requests for this teamspace, newest first.

    Uses the visibility gate like every other route here: a private teamspace
    the caller cannot see answers 404 rather than an empty 200.
    """
    await _load_visible_team(db, team_id, current_user)
    rows = (
        (
            await db.execute(
                select(TeamMembershipRequest)
                .where(
                    TeamMembershipRequest.team_id == team_id,
                    TeamMembershipRequest.user_id == current_user.id,
                )
                .order_by(TeamMembershipRequest.created_at.desc())
            )
        )
        .scalars()
        .all()
    )
    return [_join_request_response(row, current_user) for row in rows]


@router.get("/{team_id}/join-requests", response_model=list[TeamJoinRequestResponse])
async def list_join_requests(
    team_id: uuid.UUID,
    status: str | None = Query(default=None, pattern="^(pending|approved|rejected|cancelled)$"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.user)),
):
    """The teamspace's request queue and decision history. Owner or admin only."""
    await _require_owner_or_admin(db, team_id, current_user)
    decider = aliased(User)
    stmt = (
        select(TeamMembershipRequest, User, decider.username)
        .join(User, User.id == TeamMembershipRequest.user_id)
        .outerjoin(decider, decider.id == TeamMembershipRequest.decided_by)
        .where(TeamMembershipRequest.team_id == team_id)
        .order_by(TeamMembershipRequest.created_at.desc())
    )
    if status:
        stmt = stmt.where(TeamMembershipRequest.status == TeamJoinRequestStatus(status))
    rows = (await db.execute(stmt)).all()
    return [_join_request_response(row, requester, decided_by_username) for row, requester, decided_by_username in rows]


@router.post("/{team_id}/join-requests/{request_id}/approve", response_model=TeamJoinRequestResponse)
async def approve_join_request(
    team_id: uuid.UUID,
    request_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.user)),
):
    """Approve a pending request: the one path a request can become membership."""
    team = await _require_owner_or_admin(db, team_id, current_user)
    row = await _load_join_request(db, team.id, request_id, for_update=True)
    if row.status != TeamJoinRequestStatus.pending:
        raise HTTPException(status_code=409, detail=f"Request already {row.status.value}")

    # Approval grants MEMBER only; role upgrades stay owner-initiated through
    # POST /{team_id}/members. A direct member add can race this decision, so
    # recover only when the membership now exists and surface any other
    # integrity failure.
    membership = await team_membership(db, team.id, row.user_id)
    if not membership:
        try:
            async with db.begin_nested():
                db.add(TeamMembership(team_id=team.id, user_id=row.user_id, role=TeamRole.member))
                await db.flush()
        except IntegrityError:
            if not await team_membership(db, team.id, row.user_id):
                raise

    row.status = TeamJoinRequestStatus.approved
    row.decided_by = current_user.id
    row.decided_at = datetime.now(UTC)
    await inbox_sources.on_team_join_decided(
        db,
        team,
        request_id=row.id,
        requester_id=row.user_id,
        approved=True,
        actor_id=current_user.id,
    )
    await db.commit()
    await _emit_join_event(
        EventType.TEAM_JOIN_DECIDED, team, current_user, f"Approved join request for '{team.handle}'"
    )
    requester = await db.get(User, row.user_id)
    return _join_request_response(row, requester, current_user.username)


@router.post("/{team_id}/join-requests/{request_id}/reject", response_model=TeamJoinRequestResponse)
async def reject_join_request(
    team_id: uuid.UUID,
    request_id: uuid.UUID,
    req: TeamJoinDecisionRequest | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.user)),
):
    """Reject a pending request. The requester may ask again later."""
    team = await _require_owner_or_admin(db, team_id, current_user)
    row = await _load_join_request(db, team.id, request_id, for_update=True)
    if row.status != TeamJoinRequestStatus.pending:
        raise HTTPException(status_code=409, detail=f"Request already {row.status.value}")

    reason = ((req.reason if req else None) or "").strip() or None
    row.status = TeamJoinRequestStatus.rejected
    row.decided_by = current_user.id
    row.decided_at = datetime.now(UTC)
    row.decision_reason = reason
    await inbox_sources.on_team_join_decided(
        db,
        team,
        request_id=row.id,
        requester_id=row.user_id,
        approved=False,
        actor_id=current_user.id,
        reason=reason,
    )
    await db.commit()
    await _emit_join_event(
        EventType.TEAM_JOIN_DECIDED, team, current_user, f"Rejected join request for '{team.handle}'"
    )
    requester = await db.get(User, row.user_id)
    return _join_request_response(row, requester, current_user.username)


@router.delete("/{team_id}/join-requests/{request_id}", status_code=204)
async def cancel_join_request(
    team_id: uuid.UUID,
    request_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.user)),
):
    """Withdraw your own pending request. Owners reject; requesters cancel."""
    team = await _load_team(db, team_id)
    row = await _load_join_request(db, team.id, request_id, for_update=True)
    if row.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Only the requester can withdraw a request")
    if row.status != TeamJoinRequestStatus.pending:
        raise HTTPException(status_code=409, detail=f"Request already {row.status.value}")
    row.status = TeamJoinRequestStatus.cancelled
    row.decided_by = current_user.id
    row.decided_at = datetime.now(UTC)
    await inbox_sources.on_team_join_cancelled(db, team, requester_id=current_user.id)
    await db.commit()
