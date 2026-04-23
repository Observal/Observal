from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import ROLE_HIERARCHY, get_db, optional_current_user, require_role, resolve_listing
from api.sanitize import escape_like
from models.hook import HookDownload, HookListing
from models.mcp import ListingStatus
from models.user import User, UserRole
from schemas.hook import (
    HookDraftRequest,
    HookInstallRequest,
    HookInstallResponse,
    HookListingResponse,
    HookListingSummary,
    HookSubmitRequest,
    HookUpdateRequest,
)
from services.audit_helpers import audit

router = APIRouter(prefix="/api/v1/hooks", tags=["hooks"])


@router.post("/submit", response_model=HookListingResponse)
async def submit_hook(
    req: HookSubmitRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.user)),
):
    existing = await db.execute(
        select(HookListing).where(HookListing.name == req.name, HookListing.submitted_by == current_user.id)
    )
    if existing.scalars().first():
        raise HTTPException(status_code=409, detail=f"You already have a hook named '{req.name}'")

    listing = HookListing(
        name=req.name,
        version=req.version,
        description=req.description,
        owner=req.owner,
        event=req.event,
        execution_mode=req.execution_mode,
        priority=req.priority,
        handler_type=req.handler_type,
        handler_config=req.handler_config,
        input_schema=req.input_schema,
        output_schema=req.output_schema,
        scope=req.scope,
        tool_filter=req.tool_filter,
        file_pattern=req.file_pattern,
        supported_ides=req.supported_ides,
        status=ListingStatus.pending,
        submitted_by=current_user.id,
        owner_org_id=current_user.org_id,
    )
    db.add(listing)
    await db.commit()
    await db.refresh(listing)
    await audit(
        current_user, "hook.submit", resource_type="hook", resource_id=str(listing.id), resource_name=listing.name
    )
    return HookListingResponse.model_validate(listing)


@router.get("", response_model=list[HookListingSummary])
async def list_hooks(
    event: str | None = Query(None),
    scope: str | None = Query(None),
    search: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(HookListing).where(HookListing.status == ListingStatus.approved)
    if event:
        stmt = stmt.where(HookListing.event == event)
    if scope:
        stmt = stmt.where(HookListing.scope == scope)
    if search:
        safe = escape_like(search)
        stmt = stmt.where(HookListing.name.ilike(f"%{safe}%") | HookListing.description.ilike(f"%{safe}%"))
    result = await db.execute(stmt.order_by(HookListing.created_at.desc()))
    listings = [HookListingSummary.model_validate(r) for r in result.scalars().all()]
    await audit(None, "hook.list", resource_type="hook")
    return listings


@router.get("/my", response_model=list[HookListingSummary])
async def my_hooks(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.user)),
):
    stmt = (
        select(HookListing).where(HookListing.submitted_by == current_user.id).order_by(HookListing.created_at.desc())
    )
    result = await db.execute(stmt)
    listings = [HookListingSummary.model_validate(r) for r in result.scalars().all()]
    await audit(current_user, "hook.my_list", resource_type="hook")
    return listings


@router.get("/{listing_id}", response_model=HookListingResponse)
async def get_hook(
    listing_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(optional_current_user),
):
    listing = await resolve_listing(HookListing, listing_id, db, require_status=ListingStatus.approved)
    if listing:
        await audit(
            current_user, "hook.view", resource_type="hook", resource_id=str(listing.id), resource_name=listing.name
        )
        return HookListingResponse.model_validate(listing)

    listing = await resolve_listing(HookListing, listing_id, db)
    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found")

    if current_user and (
        listing.submitted_by == current_user.id
        or ROLE_HIERARCHY.get(current_user.role, 999) <= ROLE_HIERARCHY[UserRole.reviewer]
    ):
        await audit(
            current_user, "hook.view", resource_type="hook", resource_id=str(listing.id), resource_name=listing.name
        )
        return HookListingResponse.model_validate(listing)

    raise HTTPException(status_code=404, detail="Listing not found")


@router.post("/{listing_id}/install", response_model=HookInstallResponse)
async def install_hook(
    listing_id: str,
    req: HookInstallRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.user)),
):
    listing = await resolve_listing(HookListing, listing_id, db, require_status=ListingStatus.approved)
    if not listing:
        listing = await resolve_listing(HookListing, listing_id, db)
        if not listing or listing.submitted_by != current_user.id:
            raise HTTPException(status_code=404, detail="Listing not found or not approved")

    db.add(HookDownload(listing_id=listing.id, user_id=current_user.id, ide=req.ide))
    await db.commit()

    from api.routes.config import derive_endpoints
    from services.hook_config_generator import generate_hook_telemetry_config

    endpoints = derive_endpoints(request)
    config = generate_hook_telemetry_config(listing, req.ide, server_url=endpoints["api"], platform=req.platform)
    await audit(
        current_user, "hook.install", resource_type="hook", resource_id=str(listing.id), resource_name=listing.name
    )
    return HookInstallResponse(listing_id=listing.id, ide=req.ide, config_snippet=config)


@router.post("/draft", response_model=HookListingResponse)
async def save_hook_draft(
    req: HookDraftRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.user)),
):
    listing = HookListing(
        name=req.name,
        version=req.version,
        description=req.description,
        owner=req.owner or current_user.username or current_user.email,
        event=req.event,
        execution_mode=req.execution_mode,
        priority=req.priority,
        handler_type=req.handler_type,
        handler_config=req.handler_config,
        input_schema=req.input_schema,
        output_schema=req.output_schema,
        scope=req.scope,
        tool_filter=req.tool_filter,
        file_pattern=req.file_pattern,
        supported_ides=req.supported_ides,
        status=ListingStatus.draft,
        submitted_by=current_user.id,
        owner_org_id=current_user.org_id,
    )
    db.add(listing)
    await db.commit()
    await db.refresh(listing)
    await audit(
        current_user, "hook.draft.create", resource_type="hook", resource_id=str(listing.id), resource_name=listing.name
    )
    return HookListingResponse.model_validate(listing)


@router.put("/{listing_id}/draft", response_model=HookListingResponse)
async def update_hook_draft(
    listing_id: str,
    req: HookUpdateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.user)),
):
    listing = await resolve_listing(HookListing, listing_id, db)
    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found")
    if listing.submitted_by != current_user.id:
        raise HTTPException(status_code=403, detail="Not the listing owner")
    if listing.status not in (ListingStatus.draft, ListingStatus.rejected):
        raise HTTPException(status_code=400, detail="Listing is not a draft")

    for field in (
        "name",
        "version",
        "description",
        "owner",
        "event",
        "execution_mode",
        "priority",
        "handler_type",
        "handler_config",
        "input_schema",
        "output_schema",
        "scope",
        "tool_filter",
        "file_pattern",
        "supported_ides",
    ):
        val = getattr(req, field)
        if val is not None:
            setattr(listing, field, val)

    await db.commit()
    await db.refresh(listing)
    await audit(
        current_user, "hook.draft.update", resource_type="hook", resource_id=str(listing.id), resource_name=listing.name
    )
    return HookListingResponse.model_validate(listing)


@router.post("/{listing_id}/submit", response_model=HookListingResponse)
async def submit_hook_draft(
    listing_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.user)),
):
    listing = await resolve_listing(HookListing, listing_id, db)
    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found")
    if listing.submitted_by != current_user.id:
        raise HTTPException(status_code=403, detail="Not the listing owner")
    if listing.status not in (ListingStatus.draft, ListingStatus.rejected):
        raise HTTPException(status_code=400, detail="Listing is not a draft")

    if not listing.description:
        raise HTTPException(status_code=400, detail="Description is required before submitting")

    listing.status = ListingStatus.pending
    await db.commit()
    await db.refresh(listing)
    await audit(
        current_user, "hook.draft.submit", resource_type="hook", resource_id=str(listing.id), resource_name=listing.name
    )
    return HookListingResponse.model_validate(listing)


@router.delete("/{listing_id}")
async def delete_hook(
    listing_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.user)),
):
    listing = await resolve_listing(HookListing, listing_id, db)
    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found")
    is_admin = ROLE_HIERARCHY.get(current_user.role, 999) <= ROLE_HIERARCHY[UserRole.admin]
    if listing.submitted_by != current_user.id and not is_admin:
        raise HTTPException(status_code=403, detail="Not authorized")
    if listing.status == ListingStatus.approved and not is_admin:
        raise HTTPException(status_code=400, detail="Cannot delete an approved listing. Contact an admin.")

    for r in (await db.execute(select(HookDownload).where(HookDownload.listing_id == listing.id))).scalars().all():
        await db.delete(r)

    listing_name = listing.name
    await db.delete(listing)
    await db.commit()
    await audit(
        current_user, "hook.delete", resource_type="hook", resource_id=str(listing_id), resource_name=listing_name
    )
    return {"deleted": str(listing_id)}
