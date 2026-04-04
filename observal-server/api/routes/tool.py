import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import get_current_user, get_db
from models.mcp import ListingStatus
from models.tool import ToolDownload, ToolListing
from models.user import User
from schemas.tool import (
    ToolInstallRequest,
    ToolInstallResponse,
    ToolListingResponse,
    ToolListingSummary,
    ToolSubmitRequest,
)

router = APIRouter(prefix="/api/v1/tools", tags=["tools"])


@router.post("/submit", response_model=ToolListingResponse)
async def submit_tool(
    req: ToolSubmitRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    listing = ToolListing(
        name=req.name,
        version=req.version,
        description=req.description,
        owner=req.owner,
        category=req.category,
        function_schema=req.function_schema,
        auth_type=req.auth_type,
        auth_config=req.auth_config,
        endpoint_url=req.endpoint_url,
        rate_limit=req.rate_limit,
        supported_ides=req.supported_ides,
        status=ListingStatus.pending,
        submitted_by=current_user.id,
    )
    db.add(listing)
    await db.commit()
    await db.refresh(listing)
    return ToolListingResponse.model_validate(listing)


@router.get("", response_model=list[ToolListingSummary])
async def list_tools(
    category: str | None = Query(None),
    search: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(ToolListing).where(ToolListing.status == ListingStatus.approved)
    if category:
        stmt = stmt.where(ToolListing.category == category)
    if search:
        stmt = stmt.where(ToolListing.name.ilike(f"%{search}%") | ToolListing.description.ilike(f"%{search}%"))
    result = await db.execute(stmt.order_by(ToolListing.created_at.desc()))
    return [ToolListingSummary.model_validate(r) for r in result.scalars().all()]


@router.get("/{listing_id}", response_model=ToolListingResponse)
async def get_tool(listing_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(ToolListing).where(ToolListing.id == listing_id))
    listing = result.scalar_one_or_none()
    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found")
    return ToolListingResponse.model_validate(listing)


@router.post("/{listing_id}/install", response_model=ToolInstallResponse)
async def install_tool(
    listing_id: uuid.UUID,
    req: ToolInstallRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(ToolListing).where(ToolListing.id == listing_id, ToolListing.status == ListingStatus.approved)
    )
    listing = result.scalar_one_or_none()
    if not listing:
        raise HTTPException(status_code=404, detail="Approved listing not found")

    db.add(ToolDownload(listing_id=listing.id, user_id=current_user.id, ide=req.ide))
    await db.commit()

    from services.tool_config_generator import generate_tool_config

    config = generate_tool_config(listing, req.ide)
    return ToolInstallResponse(listing_id=listing.id, ide=req.ide, config_snippet=config)


@router.delete("/{listing_id}")
async def delete_tool(
    listing_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(select(ToolListing).where(ToolListing.id == listing_id))
    listing = result.scalar_one_or_none()
    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found")
    if listing.submitted_by != current_user.id and current_user.role.value != "admin":
        raise HTTPException(status_code=403, detail="Not authorized")

    for r in (await db.execute(select(ToolDownload).where(ToolDownload.listing_id == listing_id))).scalars().all():
        await db.delete(r)

    await db.delete(listing)
    await db.commit()
    return {"deleted": str(listing_id)}
