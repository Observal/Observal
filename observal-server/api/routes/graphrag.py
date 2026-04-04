import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import get_current_user, get_db
from models.graphrag import GraphRagDownload, GraphRagListing
from models.mcp import ListingStatus
from models.user import User
from schemas.graphrag import (
    GraphRagInstallRequest,
    GraphRagInstallResponse,
    GraphRagListingResponse,
    GraphRagListingSummary,
    GraphRagSubmitRequest,
)

router = APIRouter(prefix="/api/v1/graphrags", tags=["graphrags"])


@router.post("/submit", response_model=GraphRagListingResponse)
async def submit_graphrag(
    req: GraphRagSubmitRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    listing = GraphRagListing(
        name=req.name,
        version=req.version,
        description=req.description,
        owner=req.owner,
        endpoint_url=req.endpoint_url,
        auth_type=req.auth_type,
        auth_config=req.auth_config,
        query_interface=req.query_interface,
        graph_schema=req.graph_schema,
        data_sources=req.data_sources,
        embedding_model=req.embedding_model,
        chunk_strategy=req.chunk_strategy,
        supported_ides=req.supported_ides,
        status=ListingStatus.pending,
        submitted_by=current_user.id,
    )
    db.add(listing)
    await db.commit()
    await db.refresh(listing)
    return GraphRagListingResponse.model_validate(listing)


@router.get("", response_model=list[GraphRagListingSummary])
async def list_graphrags(
    query_interface: str | None = Query(None),
    search: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(GraphRagListing).where(GraphRagListing.status == ListingStatus.approved)
    if query_interface:
        stmt = stmt.where(GraphRagListing.query_interface == query_interface)
    if search:
        stmt = stmt.where(
            GraphRagListing.name.ilike(f"%{search}%") | GraphRagListing.description.ilike(f"%{search}%")
        )
    result = await db.execute(stmt.order_by(GraphRagListing.created_at.desc()))
    return [GraphRagListingSummary.model_validate(r) for r in result.scalars().all()]


@router.get("/{listing_id}", response_model=GraphRagListingResponse)
async def get_graphrag(listing_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(GraphRagListing).where(GraphRagListing.id == listing_id))
    listing = result.scalar_one_or_none()
    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found")
    return GraphRagListingResponse.model_validate(listing)


@router.post("/{listing_id}/install", response_model=GraphRagInstallResponse)
async def install_graphrag(
    listing_id: uuid.UUID,
    req: GraphRagInstallRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(GraphRagListing).where(
            GraphRagListing.id == listing_id, GraphRagListing.status == ListingStatus.approved
        )
    )
    listing = result.scalar_one_or_none()
    if not listing:
        raise HTTPException(status_code=404, detail="Approved listing not found")

    db.add(GraphRagDownload(listing_id=listing.id, user_id=current_user.id, ide=req.ide))
    await db.commit()

    from services.graphrag_config_generator import generate_graphrag_config

    config = generate_graphrag_config(listing, req.ide)
    return GraphRagInstallResponse(listing_id=listing.id, ide=req.ide, config_snippet=config)


@router.delete("/{listing_id}")
async def delete_graphrag(
    listing_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(select(GraphRagListing).where(GraphRagListing.id == listing_id))
    listing = result.scalar_one_or_none()
    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found")
    if listing.submitted_by != current_user.id and current_user.role.value != "admin":
        raise HTTPException(status_code=403, detail="Not authorized")

    for r in (
        await db.execute(select(GraphRagDownload).where(GraphRagDownload.listing_id == listing_id))
    ).scalars().all():
        await db.delete(r)

    await db.delete(listing)
    await db.commit()
    return {"deleted": str(listing_id)}
