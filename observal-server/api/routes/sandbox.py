from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import get_current_user, get_db, resolve_listing
from models.mcp import ListingStatus
from models.sandbox import SandboxDownload, SandboxListing
from models.user import User
from schemas.sandbox import (
    SandboxInstallRequest,
    SandboxInstallResponse,
    SandboxListingResponse,
    SandboxListingSummary,
    SandboxSubmitRequest,
)

router = APIRouter(prefix="/api/v1/sandboxes", tags=["sandboxes"])


@router.post("/submit", response_model=SandboxListingResponse)
async def submit_sandbox(
    req: SandboxSubmitRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    existing = await db.execute(
        select(SandboxListing).where(SandboxListing.name == req.name, SandboxListing.submitted_by == current_user.id)
    )
    if existing.scalars().first():
        raise HTTPException(status_code=409, detail=f"You already have a sandbox named '{req.name}'")

    listing = SandboxListing(
        name=req.name,
        version=req.version,
        description=req.description,
        owner=req.owner,
        runtime_type=req.runtime_type,
        image=req.image,
        dockerfile_url=req.dockerfile_url,
        resource_limits=req.resource_limits,
        network_policy=req.network_policy,
        allowed_mounts=req.allowed_mounts,
        env_vars=req.env_vars,
        entrypoint=req.entrypoint,
        supported_ides=req.supported_ides,
        status=ListingStatus.pending,
        submitted_by=current_user.id,
    )
    db.add(listing)
    await db.commit()
    await db.refresh(listing)
    return SandboxListingResponse.model_validate(listing)


@router.get("", response_model=list[SandboxListingSummary])
async def list_sandboxes(
    runtime_type: str | None = Query(None),
    search: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(SandboxListing).where(SandboxListing.status == ListingStatus.approved)
    if runtime_type:
        stmt = stmt.where(SandboxListing.runtime_type == runtime_type)
    if search:
        stmt = stmt.where(SandboxListing.name.ilike(f"%{search}%") | SandboxListing.description.ilike(f"%{search}%"))
    result = await db.execute(stmt.order_by(SandboxListing.created_at.desc()))
    return [SandboxListingSummary.model_validate(r) for r in result.scalars().all()]


@router.get("/{listing_id}", response_model=SandboxListingResponse)
async def get_sandbox(listing_id: str, db: AsyncSession = Depends(get_db)):
    listing = await resolve_listing(SandboxListing, listing_id, db)
    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found")
    return SandboxListingResponse.model_validate(listing)


@router.post("/{listing_id}/install", response_model=SandboxInstallResponse)
async def install_sandbox(
    listing_id: str,
    req: SandboxInstallRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    listing = await resolve_listing(SandboxListing, listing_id, db, require_status=ListingStatus.approved)
    if not listing:
        listing = await resolve_listing(SandboxListing, listing_id, db)
        if not listing or listing.submitted_by != current_user.id:
            raise HTTPException(status_code=404, detail="Listing not found or not approved")

    db.add(SandboxDownload(listing_id=listing.id, user_id=current_user.id, ide=req.ide))
    await db.commit()

    from services.sandbox_config_generator import generate_sandbox_config

    config = generate_sandbox_config(listing, req.ide)
    return SandboxInstallResponse(listing_id=listing.id, ide=req.ide, config_snippet=config)


@router.delete("/{listing_id}")
async def delete_sandbox(
    listing_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    listing = await resolve_listing(SandboxListing, listing_id, db)
    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found")
    if listing.submitted_by != current_user.id and current_user.role.value != "admin":
        raise HTTPException(status_code=403, detail="Not authorized")

    for r in (
        (await db.execute(select(SandboxDownload).where(SandboxDownload.listing_id == listing.id))).scalars().all()
    ):
        await db.delete(r)

    await db.delete(listing)
    await db.commit()
    return {"deleted": str(listing.id)}
