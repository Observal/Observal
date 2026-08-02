# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: Apache-2.0

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import get_db, require_role
from models.team import Team, TeamMembership, TeamRole
from models.user import User, UserRole
from schemas.team import (
    TeamCreateRequest,
    TeamMemberResponse,
    TeamMemberUpsertRequest,
    TeamResponse,
    TeamUpdateRequest,
)
from services.teamspace import count_owners, is_admin, reserve_handle, team_membership

router = APIRouter(prefix="/api/v1/teams", tags=["teams"])


def _role_value(role) -> str | None:
    if role is None:
        return None
    return role.value if hasattr(role, "value") else str(role)


async def _load_team(db: AsyncSession, team_id: uuid.UUID) -> Team:
    team = await db.get(Team, team_id)
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")
    return team


async def _require_owner_or_admin(db: AsyncSession, team_id: uuid.UUID, user: User) -> Team:
    team = await _load_team(db, team_id)
    if is_admin(user):
        return team
    membership = await team_membership(db, team_id, user.id)
    if not membership or membership.role != TeamRole.owner:
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
    rows = (
        await db.execute(
            select(Team, func.coalesce(member_counts.c.count, 0), my_roles.c.role)
            .outerjoin(member_counts, member_counts.c.team_id == Team.id)
            .outerjoin(my_roles, my_roles.c.team_id == Team.id)
            .order_by(Team.name)
        )
    ).all()
    return [
        TeamResponse(
            id=team.id,
            name=team.name,
            handle=team.handle,
            description=team.description,
            role=_role_value(role),
            member_count=int(count) if count is not None else 0,
            created_at=team.created_at,
        )
        for team, count, role in rows
    ]


@router.get("/{team_id}", response_model=TeamResponse)
async def team_detail(
    team_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.user)),
):
    team = await _load_team(db, team_id)
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
        role=role,
        created_at=team.created_at,
    )


@router.post("", response_model=TeamResponse)
async def create_team(
    req: TeamCreateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.reviewer)),
):
    raw_handle = req.handle or req.name
    try:
        handle = await reserve_handle(db, raw_handle)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    team = Team(name=req.name.strip(), handle=handle, description=req.description, created_by=current_user.id)
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
        role=_role_value(TeamRole.owner),
        member_count=1,
        created_at=team.created_at,
    )


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
        role=_role_value(TeamRole.owner),
        created_at=team.created_at,
    )


async def _team_owned_listing_counts(db: AsyncSession, team_id: uuid.UUID) -> dict[str, int]:
    """Count everything published under a teamspace, by kind.

    The team_id foreign keys are ON DELETE SET NULL, so deleting a team does not
    delete its listings: it strips their teamspace and leaves them behind.
    """
    from models.agent import Agent
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
    }
    counts: dict[str, int] = {}
    for model, (singular, plural) in labels.items():
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
                f"Teamspace '{team.handle}' still owns {detail}. Transfer or delete those listings before "
                "deleting the teamspace, otherwise their members lose access and the namespace is "
                "left claimable by someone else."
            ),
        )

    await db.delete(team)
    await db.commit()


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
