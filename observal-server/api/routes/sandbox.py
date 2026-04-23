from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import ROLE_HIERARCHY, get_db, optional_current_user, require_role, resolve_listing
from api.sanitize import escape_like
from models.mcp import ListingStatus
from models.sandbox import SandboxDownload, SandboxListing
from models.user import User, UserRole
from schemas.sandbox import (
    SandboxDraftRequest,
    SandboxInstallRequest,
    SandboxInstallResponse,
    SandboxListingResponse,
    SandboxListingSummary,
    SandboxSubmitRequest,
    SandboxUpdateRequest,
)
from services.audit_helpers import audit

router = APIRouter(prefix="/api/v1/sandboxes", tags=["sandboxes"])


@router.post("/submit", response_model=SandboxListingResponse)
async def submit_sandbox(
    req: SandboxSubmitRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.user)),
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
        owner_org_id=current_user.org_id,
    )
    db.add(listing)
    await db.commit()
    await db.refresh(listing)
    await audit(
        current_user, "sandbox.submit", resource_type="sandbox", resource_id=str(listing.id), resource_name=listing.name
    )
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
        safe = escape_like(search)
        stmt = stmt.where(SandboxListing.name.ilike(f"%{safe}%") | SandboxListing.description.ilike(f"%{safe}%"))
    result = await db.execute(stmt.order_by(SandboxListing.created_at.desc()))
    listings = [SandboxListingSummary.model_validate(r) for r in result.scalars().all()]
    await audit(None, "sandbox.list", resource_type="sandbox")
    return listings


@router.get("/my", response_model=list[SandboxListingSummary])
async def my_sandboxes(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.user)),
):
    stmt = (
        select(SandboxListing)
        .where(SandboxListing.submitted_by == current_user.id)
        .order_by(SandboxListing.created_at.desc())
    )
    result = await db.execute(stmt)
    listings = [SandboxListingSummary.model_validate(r) for r in result.scalars().all()]
    await audit(current_user, "sandbox.my_list", resource_type="sandbox")
    return listings


@router.get("/{listing_id}", response_model=SandboxListingResponse)
async def get_sandbox(
    listing_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(optional_current_user),
):
    listing = await resolve_listing(SandboxListing, listing_id, db, require_status=ListingStatus.approved)
    if listing:
        await audit(
            current_user,
            "sandbox.view",
            resource_type="sandbox",
            resource_id=str(listing.id),
            resource_name=listing.name,
        )
        return SandboxListingResponse.model_validate(listing)

    listing = await resolve_listing(SandboxListing, listing_id, db)
    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found")

    if current_user and (
        listing.submitted_by == current_user.id
        or ROLE_HIERARCHY.get(current_user.role, 999) <= ROLE_HIERARCHY[UserRole.reviewer]
    ):
        await audit(
            current_user,
            "sandbox.view",
            resource_type="sandbox",
            resource_id=str(listing.id),
            resource_name=listing.name,
        )
        return SandboxListingResponse.model_validate(listing)

    raise HTTPException(status_code=404, detail="Listing not found")


@router.post("/{listing_id}/install", response_model=SandboxInstallResponse)
async def install_sandbox(
    listing_id: str,
    req: SandboxInstallRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.user)),
):
    listing = await resolve_listing(SandboxListing, listing_id, db, require_status=ListingStatus.approved)
    if not listing:
        listing = await resolve_listing(SandboxListing, listing_id, db)
        if not listing or listing.submitted_by != current_user.id:
            raise HTTPException(status_code=404, detail="Listing not found or not approved")

    db.add(SandboxDownload(listing_id=listing.id, user_id=current_user.id, ide=req.ide))
    await db.commit()

    from api.routes.config import derive_endpoints
    from services.sandbox_config_generator import generate_sandbox_config

    endpoints = derive_endpoints(request)
    config = generate_sandbox_config(listing, req.ide, server_url=endpoints["api"])
    await audit(
        current_user,
        "sandbox.install",
        resource_type="sandbox",
        resource_id=str(listing.id),
        resource_name=listing.name,
    )
    return SandboxInstallResponse(listing_id=listing.id, ide=req.ide, config_snippet=config)


@router.post("/draft", response_model=SandboxListingResponse)
async def save_sandbox_draft(
    req: SandboxDraftRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.user)),
):
    listing = SandboxListing(
        name=req.name,
        version=req.version,
        description=req.description,
        owner=req.owner or current_user.username or current_user.email,
        runtime_type=req.runtime_type,
        image=req.image,
        dockerfile_url=req.dockerfile_url,
        resource_limits=req.resource_limits,
        network_policy=req.network_policy,
        allowed_mounts=req.allowed_mounts,
        env_vars=req.env_vars,
        entrypoint=req.entrypoint,
        supported_ides=req.supported_ides,
        status=ListingStatus.draft,
        submitted_by=current_user.id,
        owner_org_id=current_user.org_id,
    )
    db.add(listing)
    await db.commit()
    await db.refresh(listing)
    await audit(
        current_user,
        "sandbox.draft.create",
        resource_type="sandbox",
        resource_id=str(listing.id),
        resource_name=listing.name,
    )
    return SandboxListingResponse.model_validate(listing)


@router.put("/{listing_id}/draft", response_model=SandboxListingResponse)
async def update_sandbox_draft(
    listing_id: str,
    req: SandboxUpdateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.user)),
):
    listing = await resolve_listing(SandboxListing, listing_id, db)
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
        "runtime_type",
        "image",
        "dockerfile_url",
        "resource_limits",
        "network_policy",
        "allowed_mounts",
        "env_vars",
        "entrypoint",
        "supported_ides",
    ):
        val = getattr(req, field)
        if val is not None:
            setattr(listing, field, val)

    await db.commit()
    await db.refresh(listing)
    await audit(
        current_user,
        "sandbox.draft.update",
        resource_type="sandbox",
        resource_id=str(listing.id),
        resource_name=listing.name,
    )
    return SandboxListingResponse.model_validate(listing)


@router.post("/{listing_id}/submit", response_model=SandboxListingResponse)
async def submit_sandbox_draft(
    listing_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.user)),
):
    listing = await resolve_listing(SandboxListing, listing_id, db)
    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found")
    if listing.submitted_by != current_user.id:
        raise HTTPException(status_code=403, detail="Not the listing owner")
    if listing.status not in (ListingStatus.draft, ListingStatus.rejected):
        raise HTTPException(status_code=400, detail="Listing is not a draft")

    if not listing.description:
        raise HTTPException(status_code=400, detail="Description is required before submitting")
    if not listing.image:
        raise HTTPException(status_code=400, detail="Image is required before submitting")

    listing.status = ListingStatus.pending
    await db.commit()
    await db.refresh(listing)
    await audit(
        current_user,
        "sandbox.draft.submit",
        resource_type="sandbox",
        resource_id=str(listing.id),
        resource_name=listing.name,
    )
    return SandboxListingResponse.model_validate(listing)


@router.delete("/{listing_id}")
async def delete_sandbox(
    listing_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.user)),
):
    listing = await resolve_listing(SandboxListing, listing_id, db)
    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found")
    is_admin = ROLE_HIERARCHY.get(current_user.role, 999) <= ROLE_HIERARCHY[UserRole.admin]
    if listing.submitted_by != current_user.id and not is_admin:
        raise HTTPException(status_code=403, detail="Not authorized")
    if listing.status == ListingStatus.approved and not is_admin:
        raise HTTPException(status_code=400, detail="Cannot delete an approved listing. Contact an admin.")

    for r in (
        (await db.execute(select(SandboxDownload).where(SandboxDownload.listing_id == listing.id))).scalars().all()
    ):
        await db.delete(r)

    listing_name = listing.name
    await db.delete(listing)
    await db.commit()
    await audit(
        current_user, "sandbox.delete", resource_type="sandbox", resource_id=str(listing_id), resource_name=listing_name
    )
    return {"deleted": str(listing_id)}
