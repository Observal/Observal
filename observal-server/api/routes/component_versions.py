# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""Factory that generates versioning sub-routers for all 5 component types.

Usage in each type's route file::

    from api.routes.component_versions import create_version_router
    router.include_router(create_version_router("mcp", McpListing, McpVersion))
"""

from __future__ import annotations

import re
from copy import deepcopy
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from loguru import logger as optic
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: TC002

from api.deps import (
    get_db,
    get_effective_component_permission,
    may_view_unapproved,
    require_role,
    resolve_visible_listing,
)
from models.mcp import ListingStatus
from models.user import User, UserRole
from schemas.component_version import VersionPublishRequest, VersionReviewRequest  # noqa: TC001
from services.component_version_extras import ALLOWED_FIELDS, REQUIRED_FIELDS, validate_and_extract
from services.inbox import sources as inbox

# Semver pattern: X.Y.Z or X.Y.Z-prerelease
SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+(-[a-zA-Z0-9.]+)?$")

_VERSION_MANAGED_FIELDS = {
    "id",
    "listing_id",
    "version",
    "description",
    "changelog",
    "status",
    "rejection_reason",
    "download_count",
    "released_by",
    "released_at",
    "reviewed_by",
    "reviewed_at",
    "created_at",
    "is_editing",
    "editing_since",
    "editing_by",
}


async def audit(*_args, **_kwargs):
    return None


def _parse_semver(v: str) -> tuple[int, ...]:
    """Parse 'X.Y.Z' or 'X.Y.Z-pre' into (X, Y, Z) for comparison."""
    optic.trace("v={}", v)
    base = v.split("-", 1)[0]
    return tuple(int(p) for p in base.split("."))


def _version_to_dict(v, component_type: str) -> dict:
    """Serialize a version ORM object to a plain dict for API responses."""
    optic.trace("v={}, component_type={}", v, component_type)
    d = {
        "id": str(v.id),
        "listing_id": str(v.listing_id),
        "version": v.version,
        "description": v.description,
        "changelog": v.changelog,
        "status": v.status.value if hasattr(v.status, "value") else v.status,
        "rejection_reason": v.rejection_reason,
        "download_count": v.download_count,
        "supported_harnesses": v.supported_harnesses,
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
    optic.trace("listing_id={}, page={}", listing_id, page)
    listing = await resolve_visible_listing(listing_model, listing_id, db, current_user)
    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found")

    # A version carries the real payload: prompt templates, MCP commands and args,
    # hook handler config, SKILL.md. Seeing the listing is not enough to read a
    # version that has not been approved. This matters most right after a team
    # listing goes public: the listing is public immediately while its versions
    # return to the review queue, and without this filter an ordinary caller reads
    # content no global reviewer has accepted yet.
    version_filters = [version_model.listing_id == listing.id]
    if not may_view_unapproved(get_effective_component_permission(listing, current_user), current_user):
        version_filters.append(version_model.status == ListingStatus.approved)

    offset = (page - 1) * page_size
    stmt = (
        select(version_model)
        .where(*version_filters)
        .order_by(version_model.released_at.desc())
        .offset(offset)
        .limit(page_size)
    )
    result = await db.execute(stmt)
    versions = result.scalars().all()

    count_stmt = select(func.count(version_model.id)).where(*version_filters)
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
    optic.trace("listing_id={}, version={}", listing_id, version)
    listing = await resolve_visible_listing(listing_model, listing_id, db, current_user)
    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found")

    version_filters = [version_model.listing_id == listing.id, version_model.version == version]
    if not may_view_unapproved(get_effective_component_permission(listing, current_user), current_user):
        version_filters.append(version_model.status == ListingStatus.approved)
    stmt = select(version_model).where(*version_filters)
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
    optic.trace("listing_id={}, listing_model={}", listing_id, listing_model)
    if not SEMVER_RE.match(req.version):
        raise HTTPException(status_code=422, detail=f"Invalid semver string: {req.version!r}")

    listing = await resolve_visible_listing(listing_model, listing_id, db, current_user)
    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found")

    if get_effective_component_permission(listing, current_user) != "owner":
        raise HTTPException(status_code=403, detail="Only the listing owner can publish versions")

    # Duplicate check
    dup_stmt = select(version_model).where(
        version_model.listing_id == listing.id,
        version_model.version == req.version,
    )
    dup_result = await db.execute(dup_stmt)
    if dup_result.scalar_one_or_none() is not None:
        raise HTTPException(status_code=409, detail=f"Version {req.version!r} already exists for this listing")

    effective_extra = dict(req.extra or {})
    for field in REQUIRED_FIELDS.get(component_type, set()):
        if field not in effective_extra:
            value = getattr(listing, field, None)
            if value is not None:
                effective_extra[field] = value
    extra_fields = validate_and_extract(component_type, effective_extra)
    now = datetime.now(UTC)
    current_version = listing.latest_version
    snapshot = (
        {
            column.name: deepcopy(getattr(current_version, column.name))
            for column in version_model.__table__.columns
            if column.name not in _VERSION_MANAGED_FIELDS
        }
        if current_version
        else {}
    )
    if "supported_harnesses" in req.model_fields_set:
        snapshot["supported_harnesses"] = req.supported_harnesses
    ver = version_model(
        **snapshot,
        listing_id=listing.id,
        version=req.version,
        description=req.description,
        changelog=req.changelog,
        status=ListingStatus.pending,
        released_by=current_user.id,
        released_at=now,
    )
    for field_name, value in extra_fields.items():
        setattr(ver, field_name, value)

    db.add(ver)
    await db.flush()
    # This route always creates a pending version, so a review is always owed.
    await inbox.on_publish(
        db,
        listing,
        subject_type=component_type,
        actor_id=current_user.id,
        auto_approved=False,
        version=ver.version,
    )
    await db.commit()

    return _version_to_dict(ver, component_type)


async def _version_suggestions(
    listing_id: str,
    listing_model,
    version_model,
    db: AsyncSession,
    current_user: User,
) -> dict:
    optic.trace("listing_id={}, listing_model={}", listing_id, listing_model)
    listing = await resolve_visible_listing(listing_model, listing_id, db, current_user)
    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found")

    from services.versioning import parse_semver, suggest_versions

    # Use the highest existing version (including pending) to avoid duplicate suggestions
    all_ver_stmt = (
        select(version_model.version)
        .where(version_model.listing_id == listing.id)
        .order_by(version_model.released_at.desc())
    )
    all_ver_result = await db.execute(all_ver_stmt)
    all_versions = [v for (v,) in all_ver_result.all()]

    highest = listing.latest_version.version if listing.latest_version else "0.0.0"
    for v in all_versions:
        parsed = parse_semver(v)
        if parsed and parsed > (parse_semver(highest) or (0, 0, 0)):
            highest = v

    return {"current": highest, "suggestions": suggest_versions(highest)}


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
    optic.trace("listing_id={}, version={}", listing_id, version)
    listing = await resolve_visible_listing(listing_model, listing_id, db, current_user)
    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found")

    version_filters = [version_model.listing_id == listing.id, version_model.version == version]
    if not may_view_unapproved(get_effective_component_permission(listing, current_user), current_user):
        version_filters.append(version_model.status == ListingStatus.approved)
    stmt = select(version_model).where(*version_filters)
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

    # Same fact as a decision made through api/routes/review.py: the version's
    # author hears the outcome, and every reviewer's open request item for this
    # version is cleared. Delivered before the commit, in this transaction.
    await inbox.on_review_decided(
        db,
        listing,
        subject_type=component_type,
        approved=req.action == "approve",
        actor_id=current_user.id,
        version=ver.version,
        reason=req.reason if req.action != "approve" else None,
        submitter_id=ver.released_by,
    )

    await db.commit()

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

    optic.trace("component_type={}, listing_model={}", component_type, listing_model)
    router = APIRouter(tags=[f"{component_type}-versions"])

    @router.get("/{listing_id}/versions")
    async def list_versions(
        listing_id: str,
        page: int = Query(1, ge=1),
        page_size: int = Query(20, ge=1, le=100),
        db: AsyncSession = Depends(get_db),
        current_user: User = Depends(require_role(UserRole.user)),
    ):
        optic.trace("listing_id={}, page={}", listing_id, page)
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
        optic.trace("listing_id={}, version={}", listing_id, version)
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
        optic.trace("listing_id={}", listing_id)
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
        optic.trace("listing_id={}, version={}", listing_id, version)
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
        optic.trace("listing_id={}", listing_id)
        return await _version_suggestions(
            listing_id=listing_id,
            listing_model=listing_model,
            version_model=version_model,
            db=db,
            current_user=current_user,
        )

    return router
