# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""Canonical registry identifier resolution."""

import uuid
from collections import defaultdict
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import (
    apply_visibility_filter,
    check_listing_visibility_async,
    get_current_user,
    get_db,
    get_effective_agent_permission,
    get_effective_component_permission,
    may_view_unapproved,
    optional_current_user,
    resolve_listing,
    resolve_visible_listing,
)
from api.routes.agent.helpers import _load_agent
from models.agent import Agent, AgentStatus, AgentVersion
from models.agent_component import AgentComponent
from models.hook import HookListing, HookVersion
from models.mcp import ListingStatus, McpListing, McpVersion
from models.prompt import PromptListing, PromptVersion
from models.sandbox import SandboxListing, SandboxVersion
from models.skill import SkillListing, SkillVersion
from models.team import TeamRole
from models.user import User, UserRole
from services.teamspace import review_publication_to_public, team_membership

router = APIRouter(prefix="/api/v1/registry", tags=["registry"])

_LISTING_MODELS = {
    "mcp": McpListing,
    "skill": SkillListing,
    "hook": HookListing,
    "prompt": PromptListing,
    "sandbox": SandboxListing,
}
_RECONCILE_MODELS = {
    "agent": (Agent, AgentVersion),
    "mcp": (McpListing, McpVersion),
    "skill": (SkillListing, SkillVersion),
    "hook": (HookListing, HookVersion),
    "prompt": (PromptListing, PromptVersion),
    "sandbox": (SandboxListing, SandboxVersion),
}


class RegistryResolution(BaseModel):
    id: uuid.UUID
    type: str
    namespace: str
    slug: str
    qualified_name: str


RegistryItemType = Literal["agent", "mcp", "skill", "hook", "prompt", "sandbox"]


class VisibilityUpdateRequest(BaseModel):
    visibility: Literal["public", "team"]


class RegistryReconcileItem(BaseModel):
    type: RegistryItemType
    id: uuid.UUID


class RegistryReconcileRequest(BaseModel):
    items: list[RegistryReconcileItem] = Field(max_length=5000)


class RegistryReconcileResult(BaseModel):
    type: RegistryItemType
    id: uuid.UUID
    found: bool
    name: str | None = None
    namespace: str | None = None
    slug: str | None = None
    qualified_name: str | None = None
    status: str | None = None
    latest_version: str | None = None


@router.get("/resolve", response_model=RegistryResolution)
async def resolve_registry_identifier(
    type: str = Query(..., pattern="^(agent|mcp|skill|hook|prompt|sandbox)$"),
    identifier: str = Query(..., min_length=1, max_length=129),
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(optional_current_user),
):
    """Resolve a canonical or legacy registry reference without exposing hidden listings."""
    if type == "agent":
        listing = await _load_agent(
            db,
            identifier,
            prefer_user_id=current_user.id if current_user else None,
            current_user=current_user,
        )
        # _load_agent only filters on status when it resolves by name. UUID and
        # prefix lookups return any status, so gate non-approved agents here.
        if listing is not None and listing.status != AgentStatus.approved:
            permission = get_effective_agent_permission(listing, current_user)
            if not may_view_unapproved(permission, current_user):
                listing = None
    else:
        model = _LISTING_MODELS[type]
        listing = await resolve_visible_listing(
            model, identifier, db, current_user, require_status=ListingStatus.approved
        )
        if listing is None:
            listing = await resolve_visible_listing(model, identifier, db, current_user)
            if listing is not None:
                permission = get_effective_component_permission(listing, current_user)
                if not may_view_unapproved(permission, current_user):
                    listing = None

    if listing is None:
        raise HTTPException(status_code=404, detail=f"{type.title()} not found")
    return RegistryResolution(
        id=listing.id,
        type=type,
        namespace=listing.namespace,
        slug=listing.slug,
        qualified_name=listing.qualified_name,
    )


@router.patch("/{item_type}/{listing_id}/visibility")
async def update_registry_visibility(
    item_type: RegistryItemType,
    listing_id: str,
    req: VisibilityUpdateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Change a listing between public and team-member visibility."""
    if item_type == "agent":
        listing = await _load_agent(
            db,
            listing_id,
            prefer_user_id=current_user.id,
            current_user=current_user,
            include_all_statuses=True,
        )
    else:
        listing = await resolve_listing(_LISTING_MODELS[item_type], listing_id, db, current_user=current_user)
    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found")

    team_id = getattr(listing, "team_id", None)
    privileged = current_user.role in (UserRole.super_admin, UserRole.admin, UserRole.reviewer)
    if not privileged and not await check_listing_visibility_async(listing, current_user, db):
        raise HTTPException(status_code=404, detail="Listing not found")
    creator_id = getattr(listing, "created_by", None) or getattr(listing, "submitted_by", None)
    if team_id is None:
        if req.visibility == "team":
            raise HTTPException(status_code=422, detail="Team visibility requires a teamspace")
        if not privileged and creator_id != current_user.id:
            raise HTTPException(status_code=403, detail="Only the listing owner can change visibility")
    elif not privileged:
        membership = await team_membership(db, team_id, current_user.id)
        if not membership or membership.role not in (TeamRole.owner, TeamRole.reviewer):
            raise HTTPException(status_code=403, detail="Only team owners and reviewers can change visibility")

    if req.visibility == "team" and item_type != "agent":
        # Installs can pin any approved version of an agent, not just its latest,
        # so every approved version of a public agent has to keep resolving.
        public_agent_ref = await db.scalar(
            select(Agent.id)
            .join(AgentVersion, AgentVersion.agent_id == Agent.id)
            .join(AgentComponent, AgentComponent.agent_version_id == AgentVersion.id)
            .where(
                AgentComponent.component_type == item_type,
                AgentComponent.component_id == listing.id,
                Agent.is_private == False,  # noqa: E712
                Agent.deleted_at.is_(None),
                AgentVersion.status == AgentStatus.approved,
            )
            .limit(1)
        )
        if public_agent_ref is not None:
            raise HTTPException(
                status_code=409,
                detail="Cannot make this component team-only while an approved public agent version uses it",
            )

    if item_type == "agent":
        from services.agent_resolver import validate_component_ids

        component_refs = [
            {"component_type": component.component_type, "component_id": component.component_id}
            for component in listing.components
        ]
        errors = await validate_component_ids(
            component_refs,
            db,
            require_approved=False,
            current_user=current_user,
            target_team_id=listing.team_id if req.visibility == "team" else None,
            enforce_target=True,
        )
        if errors:
            raise HTTPException(
                status_code=409,
                detail="Agent visibility conflicts with one or more component visibility settings",
            )

    was_private = bool(listing.is_private)
    listing.is_private = req.visibility == "team"
    returned_to_review = review_publication_to_public(listing, current_user, was_private=was_private)

    request.state.audit_action = "registry.visibility.update"
    request.state.audit_resource_type = item_type
    request.state.audit_resource_id = str(listing.id)
    request.state.audit_resource_name = listing.qualified_name
    request.state.audit_detail = f"visibility={req.visibility}, returned_to_review={returned_to_review}"
    await db.commit()
    return {
        "id": listing.id,
        "type": item_type,
        "qualified_name": listing.qualified_name,
        "team_id": team_id,
        "visibility": listing.visibility,
        "status": listing.status.value,
        "returned_to_review": returned_to_review,
    }


@router.post("/reconcile", response_model=list[RegistryReconcileResult])
async def reconcile_registry_items(
    request: RegistryReconcileRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return canonical metadata for installed registry UUIDs in bounded queries."""
    requested: dict[str, set[uuid.UUID]] = defaultdict(set)
    for item in request.items:
        requested[item.type].add(item.id)

    found: dict[tuple[str, uuid.UUID], RegistryReconcileResult] = {}
    privileged = current_user.role in (UserRole.super_admin, UserRole.admin, UserRole.reviewer)
    for item_type, ids in requested.items():
        model, version_model = _RECONCILE_MODELS[item_type]
        stmt = (
            select(model, version_model.status, version_model.version)
            .outerjoin(version_model, model.latest_version_id == version_model.id)
            .where(model.id.in_(ids))
        )
        if item_type == "agent":
            if not privileged:
                stmt = stmt.where(
                    or_(version_model.status == AgentStatus.approved, Agent.created_by == current_user.id)
                )
            stmt = apply_visibility_filter(stmt, model, current_user)
        else:
            stmt = apply_visibility_filter(stmt, model, current_user)

        for listing, status, latest_version in (await db.execute(stmt)).all():
            status_value = "deleted" if item_type == "agent" and listing.deleted_at is not None else status
            if hasattr(status_value, "value"):
                status_value = status_value.value
            found[(item_type, listing.id)] = RegistryReconcileResult(
                type=item_type,
                id=listing.id,
                found=True,
                name=listing.name,
                namespace=listing.namespace,
                slug=listing.slug,
                qualified_name=listing.qualified_name,
                status=str(status_value) if status_value is not None else None,
                latest_version=latest_version,
            )

    return [
        found.get((item.type, item.id), RegistryReconcileResult(type=item.type, id=item.id, found=False))
        for item in request.items
    ]
