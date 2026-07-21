# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""Canonical registry identifier resolution."""

import uuid
from collections import defaultdict
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import (
    apply_visibility_filter,
    check_listing_visibility,
    get_current_user,
    get_db,
    optional_current_user,
    resolve_listing,
)
from api.routes.agent.helpers import _load_agent
from models.agent import Agent, AgentStatus, AgentVersion
from models.hook import HookListing, HookVersion
from models.mcp import ListingStatus, McpListing, McpVersion
from models.prompt import PromptListing, PromptVersion
from models.sandbox import SandboxListing, SandboxVersion
from models.skill import SkillListing, SkillVersion
from models.user import User, UserRole

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
            org_id=current_user.org_id if current_user else None,
        )
    else:
        model = _LISTING_MODELS[type]
        listing = await resolve_listing(model, identifier, db, require_status=ListingStatus.approved)
        if listing is None:
            listing = await resolve_listing(model, identifier, db)
        if listing is not None and not check_listing_visibility(listing, current_user):
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
                if current_user.org_id is not None:
                    stmt = stmt.where(or_(Agent.owner_org_id == current_user.org_id, Agent.owner_org_id.is_(None)))
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
