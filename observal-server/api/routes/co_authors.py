# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Co-author management endpoints for agents and component listings."""

from __future__ import annotations

import uuid as _uuid
from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import get_current_user, get_db, get_effective_agent_permission, get_effective_component_permission
from models.agent import Agent, AgentVersion
from models.hook import HookListing, HookVersion
from models.mcp import McpListing, McpVersion
from models.prompt import PromptListing, PromptVersion
from models.sandbox import SandboxListing, SandboxVersion
from models.skill import SkillListing, SkillVersion
from models.user import User
from services.ownership import transfer_entity_owner

router = APIRouter(prefix="/api/v1", tags=["co-authors"])

# Map entity type to model class
ENTITY_MODELS: dict[str, type] = {
    "agents": Agent,
    "mcps": McpListing,
    "hooks": HookListing,
    "sandboxes": SandboxListing,
    "prompts": PromptListing,
    "skills": SkillListing,
}

# Map entity type to version model class
VERSION_MODELS: dict[str, type] = {
    "agents": AgentVersion,
    "mcps": McpVersion,
    "hooks": HookVersion,
    "sandboxes": SandboxVersion,
    "prompts": PromptVersion,
    "skills": SkillVersion,
}


class AddCoAuthorRequest(BaseModel):
    email: str | None = None
    username: str | None = None
    user_id: str | None = None


class TransferOwnershipRequest(BaseModel):
    username: str | None = None
    email: str | None = None
    user_id: str | None = None


class CoAuthorResponse(BaseModel):
    id: str
    email: str
    username: str | None = None
    is_active: bool = True


class TransferOwnershipResponse(BaseModel):
    id: str
    owner: str
    owner_id: str
    previous_owner: str
    previous_owner_id: str


async def _get_entity_and_check_permission(
    entity_type: str,
    entity_id: _uuid.UUID,
    current_user: User,
    db: AsyncSession,
):
    """Load entity and verify the user has owner-level permission."""
    model = ENTITY_MODELS.get(entity_type)
    if not model:
        raise HTTPException(status_code=400, detail=f"Invalid entity type: {entity_type}")

    entity = await db.get(model, entity_id)
    if not entity:
        raise HTTPException(status_code=404, detail=f"{entity_type[:-1].title()} not found")

    # Check permission
    if entity_type == "agents":
        perm = get_effective_agent_permission(entity, current_user)
    else:
        perm = get_effective_component_permission(entity, current_user)

    if perm != "owner":
        raise HTTPException(status_code=403, detail="You don't have permission to manage co-authors")

    return entity


async def _get_entity_for_transfer(entity_type: str, entity_id: str, current_user: User, db: AsyncSession):
    model = ENTITY_MODELS.get(entity_type)
    if not model:
        raise HTTPException(status_code=400, detail=f"Invalid entity type: {entity_type}")

    try:
        parsed_id = _uuid.UUID(entity_id)
    except ValueError:
        result = await db.execute(select(model).where(model.name == entity_id))
        entity = result.scalar_one_or_none()
    else:
        entity = await db.get(model, parsed_id)

    if not entity:
        raise HTTPException(status_code=404, detail=f"{entity_type[:-1].title()} not found")

    owner_id = entity.created_by if entity_type == "agents" else entity.submitted_by
    if owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Only the current owner can transfer ownership")
    return entity


async def _resolve_target_user(
    db: AsyncSession,
    *,
    user_id: str | None = None,
    email: str | None = None,
    username: str | None = None,
) -> User:
    if user_id:
        try:
            parsed_id = _uuid.UUID(user_id)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="Invalid user ID") from exc
        result = await db.execute(select(User).where(User.id == parsed_id))
    elif email:
        result = await db.execute(select(User).where(User.email == email.strip().lower()))
    elif username:
        result = await db.execute(select(User).where(User.username == username.strip().lstrip("@")))
    else:
        raise HTTPException(status_code=422, detail="Provide a user")

    target_user = result.scalar_one_or_none()
    if not target_user:
        raise HTTPException(status_code=404, detail="User not found")
    return target_user


@router.post("/{entity_type}/{entity_id}/transfer-ownership", response_model=TransferOwnershipResponse)
async def transfer_ownership(
    entity_type: str,
    entity_id: str,
    req: TransferOwnershipRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    entity = await _get_entity_for_transfer(entity_type, entity_id, current_user, db)
    target_user = await _resolve_target_user(db, user_id=req.user_id, email=req.email, username=req.username)
    if not target_user:
        raise HTTPException(status_code=404, detail="User not found")
    if target_user.auth_provider == "deactivated":
        raise HTTPException(status_code=422, detail="Cannot transfer ownership to a deactivated user")
    if target_user.id == current_user.id:
        raise HTTPException(status_code=422, detail="You already own this item")

    previous_owner, previous_owner_id = transfer_entity_owner(entity, entity_type, current_user, target_user)
    await db.commit()
    await db.refresh(entity)
    return TransferOwnershipResponse(
        id=str(entity.id),
        owner=entity.owner,
        owner_id=str(target_user.id),
        previous_owner=previous_owner,
        previous_owner_id=str(previous_owner_id),
    )


@router.get("/{entity_type}/{entity_id}/co-authors", response_model=list[CoAuthorResponse])
async def list_co_authors(
    entity_type: str,
    entity_id: _uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List co-authors for an agent or component listing."""
    model = ENTITY_MODELS.get(entity_type)
    if not model:
        raise HTTPException(status_code=400, detail=f"Invalid entity type: {entity_type}")

    entity = await db.get(model, entity_id)
    if not entity:
        raise HTTPException(status_code=404, detail=f"{entity_type[:-1].title()} not found")

    co_author_ids = entity.co_authors or []
    if not co_author_ids:
        return []

    # Resolve user info
    uuids = [_uuid.UUID(str(uid)) for uid in co_author_ids]
    result = await db.execute(select(User).where(User.id.in_(uuids)))
    users = result.scalars().all()

    return [
        CoAuthorResponse(
            id=str(u.id),
            email=u.email,
            username=u.username,
            is_active=u.auth_provider != "deactivated",
        )
        for u in users
    ]


@router.post("/{entity_type}/{entity_id}/co-authors", response_model=CoAuthorResponse)
async def add_co_author(
    entity_type: str,
    entity_id: _uuid.UUID,
    req: AddCoAuthorRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Add a co-author by selected user, email, or username."""
    entity = await _get_entity_and_check_permission(entity_type, entity_id, current_user, db)
    target_user = await _resolve_target_user(db, user_id=req.user_id, email=req.email, username=req.username)

    # Can't add yourself
    owner_id = entity.created_by if entity_type == "agents" else entity.submitted_by
    if target_user.id == owner_id:
        raise HTTPException(status_code=422, detail="Owner is already implicit - no need to add as co-author")

    # Check if already a co-author
    co_authors = [str(uid) for uid in (entity.co_authors or [])]
    if str(target_user.id) in co_authors:
        raise HTTPException(status_code=409, detail="User is already a co-author")

    # Append and save
    new_list = [*co_authors, str(target_user.id)]
    entity.co_authors = new_list
    await db.commit()

    return CoAuthorResponse(
        id=str(target_user.id),
        email=target_user.email,
        username=target_user.username,
        is_active=target_user.auth_provider != "deactivated",
    )


@router.delete("/{entity_type}/{entity_id}/co-authors/{user_id}")
async def remove_co_author(
    entity_type: str,
    entity_id: _uuid.UUID,
    user_id: _uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Remove a co-author."""
    entity = await _get_entity_and_check_permission(entity_type, entity_id, current_user, db)

    co_authors = [str(uid) for uid in (entity.co_authors or [])]
    if str(user_id) not in co_authors:
        raise HTTPException(status_code=404, detail="User is not a co-author")

    co_authors.remove(str(user_id))
    entity.co_authors = co_authors
    await db.commit()

    return {"detail": "Co-author removed"}


@router.get("/{entity_type}/{entity_id}/editors", response_model=list[CoAuthorResponse])
async def list_editors(
    entity_type: str,
    entity_id: _uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List users who have released versions of this entity."""
    version_model = VERSION_MODELS.get(entity_type)
    if not version_model:
        raise HTTPException(status_code=400, detail=f"Invalid entity type: {entity_type}")

    # Determine the FK column name
    fk_col = "agent_id" if entity_type == "agents" else "listing_id"

    stmt = select(version_model.released_by).where(getattr(version_model, fk_col) == entity_id).distinct()
    result = await db.execute(stmt)
    editor_ids = [row[0] for row in result.all()]

    if not editor_ids:
        return []

    users_result = await db.execute(select(User).where(User.id.in_(editor_ids)))
    users = users_result.scalars().all()

    return [
        CoAuthorResponse(
            id=str(u.id),
            email=u.email,
            username=u.username,
            is_active=u.auth_provider != "deactivated",
        )
        for u in users
    ]
