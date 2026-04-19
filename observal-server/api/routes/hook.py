from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import get_db, require_role, resolve_listing
from models.hook import HookDownload, HookListing
from models.mcp import ListingStatus
from models.user import User, UserRole
from schemas.hook import (
    HookInstallRequest,
    HookInstallResponse,
    HookListingResponse,
    HookListingSummary,
    HookSubmitRequest,
)

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
    )
    db.add(listing)
    await db.commit()
    await db.refresh(listing)
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
        stmt = stmt.where(HookListing.name.ilike(f"%{search}%") | HookListing.description.ilike(f"%{search}%"))
    result = await db.execute(stmt.order_by(HookListing.created_at.desc()))
    return [HookListingSummary.model_validate(r) for r in result.scalars().all()]


@router.get("/{listing_id}", response_model=HookListingResponse)
async def get_hook(listing_id: str, db: AsyncSession = Depends(get_db)):
    listing = await resolve_listing(HookListing, listing_id, db)
    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found")
    return HookListingResponse.model_validate(listing)


@router.post("/{listing_id}/install", response_model=HookInstallResponse)
async def install_hook(
    listing_id: str,
    req: HookInstallRequest,
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

    from services.hook_config_generator import generate_hook_telemetry_config

    config = generate_hook_telemetry_config(listing, req.ide, platform=req.platform)
    return HookInstallResponse(listing_id=listing.id, ide=req.ide, config_snippet=config)


@router.delete("/{listing_id}")
async def delete_hook(
    listing_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.user)),
):
    listing = await resolve_listing(HookListing, listing_id, db)
    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found")
    if listing.submitted_by != current_user.id and current_user.role.value != "admin":
        raise HTTPException(status_code=403, detail="Not authorized")

    for r in (await db.execute(select(HookDownload).where(HookDownload.listing_id == listing.id))).scalars().all():
        await db.delete(r)

    await db.delete(listing)
    await db.commit()
    return {"deleted": str(listing.id)}
