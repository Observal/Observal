# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import commit_or_name_conflict, get_effective_component_permission, resolve_listing
from models.mcp import ListingStatus
from models.user import User


async def archive_listing(model, listing_id: str, db: AsyncSession, current_user: User, item_type: str) -> dict:
    listing = await resolve_listing(model, listing_id, db)
    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found")
    if get_effective_component_permission(listing, current_user) != "owner":
        raise HTTPException(status_code=403, detail="Not authorized")
    if listing.status != ListingStatus.approved:
        raise HTTPException(status_code=400, detail=f"Only approved {item_type}s can be archived")

    listing.status = ListingStatus.archived
    await commit_or_name_conflict(db, item_type)
    return {"id": str(listing.id), "name": listing.name, "status": "archived"}


async def unarchive_listing(model, listing_id: str, db: AsyncSession, current_user: User, item_type: str) -> dict:
    listing = await resolve_listing(model, listing_id, db)
    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found")
    if get_effective_component_permission(listing, current_user) != "owner":
        raise HTTPException(status_code=403, detail="Not authorized")
    if listing.status != ListingStatus.archived:
        raise HTTPException(status_code=400, detail=f"{item_type.title()} is not archived")

    listing.status = ListingStatus.approved
    await commit_or_name_conflict(db, item_type)
    return {"id": str(listing.id), "name": listing.name, "status": "approved"}


def archived_install_warning(item_type: str, name: str) -> str:
    return f"Archived {item_type} '{name}' is deprecated and may be removed from future agent pulls."
