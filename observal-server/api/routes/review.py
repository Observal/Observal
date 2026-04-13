from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import get_db, require_role, resolve_prefix_id
from models.hook import HookListing
from models.mcp import ListingStatus, McpListing
from models.prompt import PromptListing
from models.sandbox import SandboxListing
from models.skill import SkillListing
from models.user import User, UserRole
from schemas.mcp import ReviewActionRequest

router = APIRouter(prefix="/api/v1/review", tags=["review"])

LISTING_MODELS = {
    "mcp": McpListing,
    "skill": SkillListing,
    "hook": HookListing,
    "prompt": PromptListing,
    "sandbox": SandboxListing,
}


async def _find_listing(listing_id: str, db: AsyncSession):
    """Find a listing by ID, prefix, or name across all component types."""
    hits = []
    for listing_type, model in LISTING_MODELS.items():
        try:
            listing = await resolve_prefix_id(model, listing_id, db)
            hits.append((listing_type, listing))
        except HTTPException as e:
            if e.status_code == 400:
                raise e
            continue

    if len(hits) == 1:
        return hits[0]
    if len(hits) > 1:
        types = [h[0] for h in hits]
        raise HTTPException(
            status_code=400,
            detail=f"Prefix '{listing_id}' matches records across multiple types: {', '.join(types)}",
        )

    # Fallback: name-based lookup
    for listing_type, model in LISTING_MODELS.items():
        result = await db.execute(select(model).where(model.name == listing_id))
        listing = result.scalar_one_or_none()
        if listing:
            return listing_type, listing

    return None, None


@router.get("")
async def list_pending(
    type: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.reviewer)),
):

    models_to_query = {type: LISTING_MODELS[type]} if type and type in LISTING_MODELS else LISTING_MODELS
    items = []
    user_ids = set()
    for listing_type, model in models_to_query.items():
        result = await db.execute(
            select(model).where(model.status == ListingStatus.pending).order_by(model.created_at.desc())
        )
        for r in result.scalars().all():
            user_ids.add(r.submitted_by)
            item = {
                "type": listing_type,
                "id": str(r.id),
                "name": r.name,
                "description": getattr(r, "description", None) or "",
                "version": getattr(r, "version", None) or "",
                "owner": getattr(r, "owner", None) or "",
                "status": r.status.value,
                "submitted_by": r.submitted_by,
                "created_at": r.created_at.isoformat(),
            }
            # Include validation results for MCP listings
            if listing_type == "mcp" and hasattr(r, "validation_results"):
                item["mcp_validated"] = getattr(r, "mcp_validated", False)
                item["validation_results"] = [
                    {
                        "stage": vr.stage,
                        "passed": vr.passed,
                        "details": vr.details,
                    }
                    for vr in r.validation_results
                ]
            items.append(item)

    # Resolve user UUIDs to display names
    user_map = {}
    if user_ids:
        result = await db.execute(select(User).where(User.id.in_(user_ids)))
        for u in result.scalars().all():
            user_map[u.id] = u.name or u.email

    for item in items:
        uid = item["submitted_by"]
        item["submitted_by"] = user_map.get(uid, str(uid))

    return items


@router.get("/{listing_id}")
async def get_review(
    listing_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.reviewer)),
):
    listing_type, listing = await _find_listing(listing_id, db)
    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found")
    result = {
        "type": listing_type,
        "id": str(listing.id),
        "name": listing.name,
        "description": getattr(listing, "description", None) or "",
        "version": getattr(listing, "version", None) or "",
        "owner": getattr(listing, "owner", None) or "",
        "status": listing.status.value,
        "submitted_by": str(listing.submitted_by),
        "created_at": listing.created_at.isoformat(),
    }
    if listing_type == "mcp" and hasattr(listing, "validation_results"):
        result["mcp_validated"] = getattr(listing, "mcp_validated", False)
        result["validation_results"] = [
            {"stage": vr.stage, "passed": vr.passed, "details": vr.details} for vr in listing.validation_results
        ]
    return result


@router.post("/{listing_id}/approve")
async def approve(
    listing_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.reviewer)),
):
    listing_type, listing = await _find_listing(listing_id, db)
    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found")
    listing.status = ListingStatus.approved
    await db.commit()
    await db.refresh(listing)
    return {"type": listing_type, "id": str(listing.id), "name": listing.name, "status": listing.status.value}


@router.post("/{listing_id}/reject")
async def reject(
    listing_id: str,
    req: ReviewActionRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.reviewer)),
):
    listing_type, listing = await _find_listing(listing_id, db)
    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found")
    listing.status = ListingStatus.rejected
    listing.rejection_reason = req.reason
    await db.commit()
    await db.refresh(listing)
    return {"type": listing_type, "id": str(listing.id), "name": listing.name, "status": listing.status.value}
