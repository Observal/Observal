import logging
from datetime import UTC, datetime

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import ROLE_HIERARCHY, get_db, optional_current_user, require_role, resolve_listing
from api.routes.component_versions import create_version_router
from api.sanitize import escape_like
from database import async_session
from models.mcp import ListingStatus, McpDownload, McpListing, McpValidationResult, McpVersion
from models.user import User, UserRole
from schemas.mcp import (
    ClientAnalysis,
    McpAnalyzeRequest,
    McpAnalyzeResponse,
    McpDraftRequest,
    McpInstallRequest,
    McpInstallResponse,
    McpListingResponse,
    McpListingSummary,
    McpSubmitRequest,
    McpUpdateRequest,
)
from services.audit_helpers import audit
from services.config_generator import generate_config
from services.mcp_validator import analyze_repo, run_validation

router = APIRouter(prefix="/api/v1/mcps", tags=["mcp"])
logger = logging.getLogger(__name__)


@router.post("/analyze", response_model=McpAnalyzeResponse)
async def analyze_mcp(
    req: McpAnalyzeRequest,
    current_user: User = Depends(require_role(UserRole.user)),
):
    result = await analyze_repo(req.git_url)
    await audit(current_user, "mcp.analyze", resource_type="mcp", detail=req.git_url)
    return McpAnalyzeResponse(**result)


async def _store_client_analysis(listing: McpListing, analysis: ClientAnalysis, db: AsyncSession) -> None:
    """Store validation results from client-side (CLI) analysis."""
    await db.execute(delete(McpValidationResult).where(McpValidationResult.listing_id == listing.id))

    has_entry = bool(analysis.entry_point or analysis.framework)
    tool_count = len(analysis.tools)
    issue_count = len(analysis.issues)

    if analysis.framework:
        listing.framework = analysis.framework
    if analysis.command and not listing.command:
        listing.command = analysis.command
    if analysis.args and not listing.args:
        listing.args = analysis.args
    if analysis.docker_image and not listing.docker_image:
        listing.docker_image = analysis.docker_image

    if has_entry:
        detail = "Client-side analysis: found entry point"
        if analysis.framework:
            detail += f" ({analysis.framework})"
        listing.mcp_validated = True
    else:
        detail = "Client-side analysis: no recognized MCP framework detected"
        listing.mcp_validated = True

    db.add(McpValidationResult(listing_id=listing.id, stage="clone_and_inspect", passed=has_entry, details=detail))

    if tool_count or issue_count:
        manifest_detail = f"Client-side analysis: {tool_count} tool(s) found"
        if analysis.issues:
            manifest_detail += "\nIssues:\n- " + "\n- ".join(analysis.issues)
        db.add(
            McpValidationResult(
                listing_id=listing.id,
                stage="manifest_validation",
                passed=issue_count == 0,
                details=manifest_detail,
            )
        )

    await db.commit()


async def _run_validation_background(listing_id: str) -> None:
    """Run validation in the background with its own DB session."""
    async with async_session() as db:
        result = await db.execute(select(McpListing).where(McpListing.id == listing_id))
        listing = result.scalar_one_or_none()
        if not listing:
            return
        try:
            await run_validation(listing, db)
        except Exception:
            logger.exception("Background validation failed for listing %s", listing_id)


@router.post("/submit", response_model=McpListingResponse)
async def submit_mcp(
    req: McpSubmitRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.user)),
):
    # Prevent duplicate names for the same user.
    # Pending/rejected listings are replaced automatically so the user isn't
    # blocked when re-submitting after a mistake.  Approved listings are
    # protected — use the update flow instead.
    existing = (
        (
            await db.execute(
                select(McpListing).where(McpListing.name == req.name, McpListing.submitted_by == current_user.id)
            )
        )
        .scalars()
        .first()
    )
    if existing:
        if existing.status == ListingStatus.approved:
            raise HTTPException(status_code=409, detail=f"You already have an approved listing named '{req.name}'")
        # Replace the old pending/rejected listing
        await db.delete(existing)
        await db.flush()

    listing = McpListing(
        name=req.name,
        category=req.category,
        owner=req.owner,
        submitted_by=current_user.id,
        owner_org_id=current_user.org_id,
    )
    db.add(listing)
    await db.flush()

    version = McpVersion(
        listing_id=listing.id,
        version=req.version,
        description=req.description,
        transport=req.transport or ("sse" if req.url and not req.command else "stdio" if req.command else None),
        framework=req.framework,
        docker_image=req.docker_image,
        command=req.command,
        args=req.args,
        url=req.url,
        headers=[h.model_dump() for h in req.headers] if req.headers else None,
        auto_approve=req.auto_approve,
        environment_variables=[ev.model_dump() for ev in req.environment_variables],
        supported_ides=req.supported_ides,
        setup_instructions=req.setup_instructions,
        changelog=req.changelog,
        source_url=req.git_url,
        status=ListingStatus.pending,
        released_by=current_user.id,
        released_at=datetime.now(UTC),
    )
    db.add(version)
    await db.flush()

    listing.latest_version_id = version.id
    await db.commit()
    await db.refresh(listing)

    if req.client_analysis:
        # CLI already cloned and analyzed locally — store results directly
        await _store_client_analysis(listing, req.client_analysis, db)
    elif req.git_url:
        # Only run background validation if we have a git URL to clone
        background_tasks.add_task(_run_validation_background, str(listing.id))
    # Direct config submissions (no git_url) skip validation — config is user-provided

    await audit(
        current_user, "mcp.submit", resource_type="mcp", resource_id=str(listing.id), resource_name=listing.name
    )
    return McpListingResponse.model_validate(listing)


@router.get("", response_model=list[McpListingSummary])
async def list_mcps(
    category: str | None = Query(None),
    search: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    stmt = (
        select(McpListing)
        .join(McpVersion, McpListing.latest_version_id == McpVersion.id)
        .where(McpVersion.status == ListingStatus.approved)
    )
    if category:
        stmt = stmt.where(McpListing.category == category)
    if search:
        safe = escape_like(search)
        stmt = stmt.where(McpListing.name.ilike(f"%{safe}%") | McpVersion.description.ilike(f"%{safe}%"))
    result = await db.execute(stmt.order_by(McpListing.created_at.desc()))
    listings = [McpListingSummary.model_validate(r) for r in result.scalars().all()]
    await audit(None, "mcp.list", resource_type="mcp")
    return listings


@router.get("/my", response_model=list[McpListingSummary])
async def my_mcps(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.user)),
):
    stmt = select(McpListing).where(McpListing.submitted_by == current_user.id).order_by(McpListing.created_at.desc())
    result = await db.execute(stmt)
    listings = [McpListingSummary.model_validate(r) for r in result.scalars().all()]
    await audit(current_user, "mcp.my_list", resource_type="mcp")
    return listings


@router.get("/{listing_id}", response_model=McpListingResponse)
async def get_mcp(
    listing_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(optional_current_user),
):
    listing = await resolve_listing(McpListing, listing_id, db, require_status=ListingStatus.approved)
    if listing:
        await audit(
            current_user, "mcp.view", resource_type="mcp", resource_id=str(listing.id), resource_name=listing.name
        )
        return McpListingResponse.model_validate(listing)

    listing = await resolve_listing(McpListing, listing_id, db)
    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found")

    if current_user and (
        listing.submitted_by == current_user.id
        or ROLE_HIERARCHY.get(current_user.role, 999) <= ROLE_HIERARCHY[UserRole.reviewer]
    ):
        await audit(
            current_user, "mcp.view", resource_type="mcp", resource_id=str(listing.id), resource_name=listing.name
        )
        return McpListingResponse.model_validate(listing)

    raise HTTPException(status_code=404, detail="Listing not found")


@router.post("/{listing_id}/install", response_model=McpInstallResponse)
async def install_mcp(
    listing_id: str,
    req: McpInstallRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.user)),
):
    listing = await resolve_listing(McpListing, listing_id, db, require_status=ListingStatus.approved)
    if not listing:
        listing = await resolve_listing(McpListing, listing_id, db)
        if not listing or listing.submitted_by != current_user.id:
            raise HTTPException(status_code=404, detail="Listing not found or not approved")

    db.add(McpDownload(listing_id=listing.id, user_id=current_user.id, ide=req.ide))
    await db.commit()

    from api.routes.config import derive_endpoints

    endpoints = derive_endpoints(request)
    snippet = generate_config(
        listing,
        req.ide,
        observal_url=endpoints["otlp_http"],
        env_values=req.env_values,
        header_values=req.header_values,
    )
    await audit(
        current_user, "mcp.install", resource_type="mcp", resource_id=str(listing.id), resource_name=listing.name
    )
    return McpInstallResponse(listing_id=listing.id, ide=req.ide, config_snippet=snippet)


@router.post("/draft", response_model=McpListingResponse)
async def save_mcp_draft(
    req: McpDraftRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.user)),
):
    listing = McpListing(
        name=req.name,
        category=req.category,
        owner=req.owner or current_user.username or current_user.email,
        submitted_by=current_user.id,
        owner_org_id=current_user.org_id,
    )
    db.add(listing)
    await db.flush()

    version = McpVersion(
        listing_id=listing.id,
        version=req.version,
        description=req.description,
        transport=req.transport or ("sse" if req.url and not req.command else "stdio" if req.command else None),
        framework=req.framework,
        docker_image=req.docker_image,
        command=req.command,
        args=req.args,
        url=req.url,
        headers=[h.model_dump() for h in req.headers] if req.headers else None,
        auto_approve=req.auto_approve,
        environment_variables=[ev.model_dump() for ev in req.environment_variables],
        supported_ides=req.supported_ides,
        setup_instructions=req.setup_instructions,
        changelog=req.changelog,
        source_url=req.git_url,
        status=ListingStatus.draft,
        released_by=current_user.id,
        released_at=datetime.now(UTC),
    )
    db.add(version)
    await db.flush()

    listing.latest_version_id = version.id
    await db.commit()
    await db.refresh(listing)
    await audit(
        current_user, "mcp.draft.create", resource_type="mcp", resource_id=str(listing.id), resource_name=listing.name
    )
    return McpListingResponse.model_validate(listing)


@router.put("/{listing_id}/draft", response_model=McpListingResponse)
async def update_mcp_draft(
    listing_id: str,
    req: McpUpdateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.user)),
):
    listing = await resolve_listing(McpListing, listing_id, db)
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
        "category",
        "owner",
        "git_url",
        "framework",
        "docker_image",
        "command",
        "args",
        "url",
        "auto_approve",
        "transport",
        "supported_ides",
        "setup_instructions",
        "changelog",
    ):
        val = getattr(req, field)
        if val is not None:
            setattr(listing, field, val)

    if req.headers is not None:
        listing.headers = [h.model_dump() for h in req.headers]
    if req.environment_variables is not None:
        listing.environment_variables = [ev.model_dump() for ev in req.environment_variables]

    await db.commit()
    await db.refresh(listing)
    await audit(
        current_user, "mcp.draft.update", resource_type="mcp", resource_id=str(listing.id), resource_name=listing.name
    )
    return McpListingResponse.model_validate(listing)


@router.post("/{listing_id}/submit", response_model=McpListingResponse)
async def submit_mcp_draft(
    listing_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.user)),
):
    listing = await resolve_listing(McpListing, listing_id, db)
    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found")
    if listing.submitted_by != current_user.id:
        raise HTTPException(status_code=403, detail="Not the listing owner")
    if listing.status not in (ListingStatus.draft, ListingStatus.rejected):
        raise HTTPException(status_code=400, detail="Listing is not a draft")

    if not listing.description:
        raise HTTPException(status_code=400, detail="Description is required before submitting")
    if not listing.git_url and not listing.command and not listing.url:
        raise HTTPException(status_code=400, detail="At least one of git_url, command, or url is required")

    listing.status = ListingStatus.pending
    await db.commit()
    await db.refresh(listing)
    await audit(
        current_user, "mcp.draft.submit", resource_type="mcp", resource_id=str(listing.id), resource_name=listing.name
    )
    return McpListingResponse.model_validate(listing)


@router.delete("/{listing_id}")
async def delete_mcp(
    listing_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.user)),
):
    from models.feedback import Feedback

    listing = await resolve_listing(McpListing, listing_id, db)
    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found")
    is_admin = ROLE_HIERARCHY.get(current_user.role, 999) <= ROLE_HIERARCHY[UserRole.admin]
    if listing.submitted_by != current_user.id and not is_admin:
        raise HTTPException(status_code=403, detail="Not authorized")
    if listing.status == ListingStatus.approved and not is_admin:
        raise HTTPException(status_code=400, detail="Cannot delete an approved listing. Contact an admin.")

    for r in (
        (await db.execute(select(Feedback).where(Feedback.listing_id == listing.id, Feedback.listing_type == "mcp")))
        .scalars()
        .all()
    ):
        await db.delete(r)
    for r in (await db.execute(select(McpDownload).where(McpDownload.listing_id == listing.id))).scalars().all():
        await db.delete(r)

    # Break the circular FK (listing → latest_version → listing) before delete
    listing_name = listing.name
    listing.latest_version_id = None
    listing.latest_version = None
    await db.flush()
    # Delete versions explicitly to avoid SQLAlchemy circular dependency detection
    for ver in list(listing.versions):
        await db.delete(ver)
    await db.flush()
    await db.delete(listing)
    await db.commit()
    await audit(
        current_user, "mcp.delete", resource_type="mcp", resource_id=str(listing_id), resource_name=listing_name
    )
    return {"deleted": str(listing_id)}


# --- Version sub-routes ---
router.include_router(create_version_router("mcp", McpListing, McpVersion))
