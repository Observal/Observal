import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import get_db, require_role, resolve_listing
from database import async_session
from models.mcp import ListingStatus, McpDownload, McpListing, McpValidationResult
from models.user import User, UserRole
from schemas.mcp import (
    ClientAnalysis,
    McpAnalyzeRequest,
    McpAnalyzeResponse,
    McpInstallRequest,
    McpInstallResponse,
    McpListingResponse,
    McpListingSummary,
    McpSubmitRequest,
)
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
    return McpAnalyzeResponse(**result)


async def _store_client_analysis(listing: McpListing, analysis: ClientAnalysis, db: AsyncSession) -> None:
    """Store validation results from client-side (CLI) analysis."""
    has_entry = bool(analysis.entry_point or analysis.framework)
    tool_count = len(analysis.tools)
    issue_count = len(analysis.issues)

    if analysis.framework:
        listing.framework = analysis.framework

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
        version=req.version,
        git_url=req.git_url,
        description=req.description,
        category=req.category,
        owner=req.owner,
        framework=req.framework,
        docker_image=req.docker_image,
        supported_ides=req.supported_ides,
        environment_variables=[ev.model_dump() for ev in req.environment_variables],
        setup_instructions=req.setup_instructions,
        changelog=req.changelog,
        status=ListingStatus.pending,
        submitted_by=current_user.id,
    )
    db.add(listing)
    await db.commit()
    await db.refresh(listing)

    if req.client_analysis:
        # CLI already cloned and analyzed locally — store results directly
        await _store_client_analysis(listing, req.client_analysis, db)
    else:
        # No client-side analysis; fall back to server-side background validation
        background_tasks.add_task(_run_validation_background, str(listing.id))

    return McpListingResponse.model_validate(listing)


@router.get("", response_model=list[McpListingSummary])
async def list_mcps(
    category: str | None = Query(None),
    search: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(McpListing).where(McpListing.status == ListingStatus.approved)
    if category:
        stmt = stmt.where(McpListing.category == category)
    if search:
        stmt = stmt.where(McpListing.name.ilike(f"%{search}%") | McpListing.description.ilike(f"%{search}%"))
    result = await db.execute(stmt.order_by(McpListing.created_at.desc()))
    return [McpListingSummary.model_validate(r) for r in result.scalars().all()]


@router.get("/{listing_id}", response_model=McpListingResponse)
async def get_mcp(listing_id: str, db: AsyncSession = Depends(get_db)):
    listing = await resolve_listing(McpListing, listing_id, db)
    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found")
    return McpListingResponse.model_validate(listing)


@router.post("/{listing_id}/install", response_model=McpInstallResponse)
async def install_mcp(
    listing_id: str,
    req: McpInstallRequest,
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

    snippet = generate_config(listing, req.ide, env_values=req.env_values)
    return McpInstallResponse(listing_id=listing.id, ide=req.ide, config_snippet=snippet)


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
    if listing.submitted_by != current_user.id and current_user.role.value != "admin":
        raise HTTPException(status_code=403, detail="Not authorized")

    for r in (
        (await db.execute(select(Feedback).where(Feedback.listing_id == listing.id, Feedback.listing_type == "mcp")))
        .scalars()
        .all()
    ):
        await db.delete(r)
    for r in (await db.execute(select(McpDownload).where(McpDownload.listing_id == listing.id))).scalars().all():
        await db.delete(r)

    await db.delete(listing)
    await db.commit()
    return {"deleted": str(listing.id)}
