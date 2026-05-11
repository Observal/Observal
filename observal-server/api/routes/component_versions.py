# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Factory that generates versioning sub-routers for all 5 component types.

Usage in each type's route file::

    from api.routes.component_versions import create_version_router
    router.include_router(create_version_router("mcp", McpListing, McpVersion))
"""

from __future__ import annotations

import re
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: TC002

from api.deps import get_db, require_role, resolve_listing
from models.mcp import ListingStatus
from models.user import User, UserRole
from schemas.component_version import VersionPublishRequest, VersionReviewRequest  # noqa: TC001
from services.audit_helpers import audit
from services.component_version_extras import ALLOWED_FIELDS, validate_and_extract

# Semver pattern: X.Y.Z or X.Y.Z-prerelease
SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+(-[a-zA-Z0-9.]+)?$")


def _parse_semver(v: str) -> tuple[int, ...]:
    """Parse 'X.Y.Z' or 'X.Y.Z-pre' into (X, Y, Z) for comparison."""
    base = v.split("-", 1)[0]
    return tuple(int(p) for p in base.split("."))


def _version_to_dict(v, component_type: str) -> dict:
    """Serialize a version ORM object to a plain dict for API responses."""
    d = {
        "id": str(v.id),
        "listing_id": str(v.listing_id),
        "version": v.version,
        "description": v.description,
        "changelog": v.changelog,
        "status": v.status.value if hasattr(v.status, "value") else v.status,
        "rejection_reason": v.rejection_reason,
        "download_count": v.download_count,
        "supported_ides": v.supported_ides,
        "released_by": str(v.released_by),
        "released_at": v.released_at,
        "created_at": v.created_at,
    }
    for attr in ALLOWED_FIELDS.get(component_type, set()):
        if hasattr(v, attr):
            d[attr] = getattr(v, attr)
    return d


# ---------------------------------------------------------------------------
# Standalone async functions (exposed for direct testing)
# ---------------------------------------------------------------------------


async def _list_versions(
    listing_id: str,
    page: int,
    page_size: int,
    listing_model,
    version_model,
    component_type: str,
    db: AsyncSession,
    current_user: User,
) -> dict:
    listing = await resolve_listing(listing_model, listing_id, db)
    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found")

    offset = (page - 1) * page_size
    stmt = (
        select(version_model)
        .where(version_model.listing_id == listing.id)
        .order_by(version_model.released_at.desc())
        .offset(offset)
        .limit(page_size)
    )
    result = await db.execute(stmt)
    versions = result.scalars().all()

    count_stmt = select(func.count(version_model.id)).where(version_model.listing_id == listing.id)
    total = (await db.execute(count_stmt)).scalar() or 0

    return {
        "items": [_version_to_dict(v, component_type) for v in versions],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


async def _get_version(
    listing_id: str,
    version: str,
    listing_model,
    version_model,
    component_type: str,
    db: AsyncSession,
    current_user: User,
) -> dict:
    listing = await resolve_listing(listing_model, listing_id, db)
    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found")

    stmt = select(version_model).where(
        version_model.listing_id == listing.id,
        version_model.version == version,
    )
    result = await db.execute(stmt)
    ver = result.scalar_one_or_none()
    if not ver:
        raise HTTPException(status_code=404, detail="Version not found")

    return _version_to_dict(ver, component_type)


async def _publish_version(
    listing_id: str,
    req: VersionPublishRequest,
    listing_model,
    version_model,
    component_type: str,
    db: AsyncSession,
    current_user: User,
) -> dict:
    if not SEMVER_RE.match(req.version):
        raise HTTPException(status_code=422, detail=f"Invalid semver string: {req.version!r}")

    listing = await resolve_listing(listing_model, listing_id, db)
    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found")

    if listing.submitted_by != current_user.id:
        raise HTTPException(status_code=403, detail="Only the listing owner can publish versions")

    # Duplicate check
    dup_stmt = select(version_model).where(
        version_model.listing_id == listing.id,
        version_model.version == req.version,
    )
    dup_result = await db.execute(dup_stmt)
    if dup_result.scalar_one_or_none() is not None:
        raise HTTPException(status_code=409, detail=f"Version {req.version!r} already exists for this listing")

    extra_fields = validate_and_extract(component_type, req.extra)
    now = datetime.now(UTC)
    ver = version_model(
        listing_id=listing.id,
        version=req.version,
        description=req.description,
        changelog=req.changelog,
        supported_ides=req.supported_ides or [],
        status=ListingStatus.pending,
        released_by=current_user.id,
        released_at=now,
    )
    for field_name, value in extra_fields.items():
        setattr(ver, field_name, value)
    db.add(ver)
    await db.commit()

    await audit(
        current_user,
        f"{component_type}.version.publish",
        resource_type=component_type,
        resource_id=str(listing.id),
        resource_name=getattr(listing, "name", ""),
        detail=req.version,
    )

    return _version_to_dict(ver, component_type)


async def _version_suggestions(
    listing_id: str,
    listing_model,
    db: AsyncSession,
    current_user: User,
) -> dict:
    listing = await resolve_listing(listing_model, listing_id, db)
    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found")

    from services.versioning import suggest_versions

    current = listing.latest_version.version if listing.latest_version else "0.0.0"
    return {"current": current, "suggestions": suggest_versions(current)}


async def _review_version(
    listing_id: str,
    version: str,
    req: VersionReviewRequest,
    listing_model,
    version_model,
    component_type: str,
    db: AsyncSession,
    current_user: User,
) -> dict:
    listing = await resolve_listing(listing_model, listing_id, db)
    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found")

    stmt = select(version_model).where(
        version_model.listing_id == listing.id,
        version_model.version == version,
    )
    result = await db.execute(stmt)
    ver = result.scalar_one_or_none()
    if not ver:
        raise HTTPException(status_code=404, detail="Version not found")

    if ver.status != ListingStatus.pending:
        raise HTTPException(
            status_code=422, detail=f"Version is {ver.status.value!r}, only pending versions can be reviewed"
        )

    if req.action == "approve":
        ver.status = ListingStatus.approved
        ver.rejection_reason = None
        # Only update latest if this version is newer than current latest
        current_latest = listing.latest_version
        if not current_latest or _parse_semver(ver.version) >= _parse_semver(current_latest.version):
            listing.latest_version_id = ver.id
    else:
        ver.status = ListingStatus.rejected
        ver.rejection_reason = req.reason

    ver.reviewed_by = current_user.id
    ver.reviewed_at = datetime.now(UTC)

    await db.commit()

    await audit(
        current_user,
        f"{component_type}.version.{req.action}",
        resource_type=component_type,
        resource_id=str(listing.id),
        resource_name=getattr(listing, "name", ""),
        detail=version,
    )

    return {
        "version": version,
        "new_status": ver.status.value,
        "reason": ver.rejection_reason,
    }


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def create_version_router(
    component_type: str,
    listing_model,
    version_model,
) -> APIRouter:
    """Return an APIRouter with 4 version endpoints for the given component type."""

    router = APIRouter(tags=[f"{component_type}-versions"])

    @router.get("/{listing_id}/versions")
    async def list_versions(
        listing_id: str,
        page: int = Query(1, ge=1),
        page_size: int = Query(20, ge=1, le=100),
        db: AsyncSession = Depends(get_db),
        current_user: User = Depends(require_role(UserRole.user)),
    ):
        return await _list_versions(
            listing_id=listing_id,
            page=page,
            page_size=page_size,
            listing_model=listing_model,
            version_model=version_model,
            component_type=component_type,
            db=db,
            current_user=current_user,
        )

    @router.get("/{listing_id}/versions/{version}")
    async def get_version(
        listing_id: str,
        version: str,
        db: AsyncSession = Depends(get_db),
        current_user: User = Depends(require_role(UserRole.user)),
    ):
        return await _get_version(
            listing_id=listing_id,
            version=version,
            listing_model=listing_model,
            version_model=version_model,
            component_type=component_type,
            db=db,
            current_user=current_user,
        )

    @router.post("/{listing_id}/versions")
    async def publish_version(
        listing_id: str,
        req: VersionPublishRequest,
        db: AsyncSession = Depends(get_db),
        current_user: User = Depends(require_role(UserRole.user)),
    ):
        return await _publish_version(
            listing_id=listing_id,
            req=req,
            listing_model=listing_model,
            version_model=version_model,
            component_type=component_type,
            db=db,
            current_user=current_user,
        )

    @router.post("/{listing_id}/versions/{version}/review")
    async def review_version(
        listing_id: str,
        version: str,
        req: VersionReviewRequest,
        db: AsyncSession = Depends(get_db),
        current_user: User = Depends(require_role(UserRole.reviewer)),
    ):
        return await _review_version(
            listing_id=listing_id,
            version=version,
            req=req,
            listing_model=listing_model,
            version_model=version_model,
            component_type=component_type,
            db=db,
            current_user=current_user,
        )

    @router.get("/{listing_id}/version-suggestions")
    async def version_suggestions(
        listing_id: str,
        db: AsyncSession = Depends(get_db),
        current_user: User = Depends(require_role(UserRole.user)),
    ):
        return await _version_suggestions(
            listing_id=listing_id,
            listing_model=listing_model,
            db=db,
            current_user=current_user,
        )

    return router
