# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""Canonical registry identifier resolution."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import check_listing_visibility, get_db, optional_current_user, resolve_listing
from api.routes.agent.helpers import _load_agent
from models.hook import HookListing
from models.mcp import ListingStatus, McpListing
from models.prompt import PromptListing
from models.sandbox import SandboxListing
from models.skill import SkillListing
from models.user import User

router = APIRouter(prefix="/api/v1/registry", tags=["registry"])

_LISTING_MODELS = {
    "mcp": McpListing,
    "skill": SkillListing,
    "hook": HookListing,
    "prompt": PromptListing,
    "sandbox": SandboxListing,
}


class RegistryResolution(BaseModel):
    id: uuid.UUID
    type: str
    namespace: str
    slug: str
    qualified_name: str


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
