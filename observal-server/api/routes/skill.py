from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import ROLE_HIERARCHY, get_db, optional_current_user, require_role, resolve_listing
from api.sanitize import escape_like
from models.mcp import ListingStatus
from models.skill import SkillDownload, SkillListing
from models.user import User, UserRole
from schemas.skill import (
    SkillDraftRequest,
    SkillInstallRequest,
    SkillInstallResponse,
    SkillListingResponse,
    SkillListingSummary,
    SkillSubmitRequest,
    SkillUpdateRequest,
)
from services.audit_helpers import audit

router = APIRouter(prefix="/api/v1/skills", tags=["skills"])


@router.post("/submit", response_model=SkillListingResponse)
async def submit_skill(
    req: SkillSubmitRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.user)),
):
    existing = await db.execute(
        select(SkillListing).where(SkillListing.name == req.name, SkillListing.submitted_by == current_user.id)
    )
    if existing.scalars().first():
        raise HTTPException(status_code=409, detail=f"You already have a skill named '{req.name}'")

    listing = SkillListing(
        name=req.name,
        version=req.version,
        description=req.description,
        owner=req.owner,
        git_url=req.git_url,
        skill_path=req.skill_path,
        target_agents=req.target_agents,
        task_type=req.task_type,
        triggers=req.triggers,
        slash_command=req.slash_command,
        has_scripts=req.has_scripts,
        has_templates=req.has_templates,
        supported_ides=req.supported_ides,
        is_power=req.is_power,
        power_md=req.power_md,
        mcp_server_config=req.mcp_server_config,
        activation_keywords=req.activation_keywords,
        status=ListingStatus.pending,
        submitted_by=current_user.id,
        owner_org_id=current_user.org_id,
    )
    db.add(listing)
    await db.commit()
    await db.refresh(listing)
    await audit(
        current_user, "skill.submit", resource_type="skill", resource_id=str(listing.id), resource_name=listing.name
    )
    return SkillListingResponse.model_validate(listing)


@router.get("", response_model=list[SkillListingSummary])
async def list_skills(
    task_type: str | None = Query(None),
    target_agent: str | None = Query(None),
    search: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(SkillListing).where(SkillListing.status == ListingStatus.approved)
    if task_type:
        stmt = stmt.where(SkillListing.task_type == task_type)
    if target_agent:
        stmt = stmt.where(SkillListing.target_agents.cast(str).ilike(f"%{escape_like(target_agent)}%"))
    if search:
        safe = escape_like(search)
        stmt = stmt.where(SkillListing.name.ilike(f"%{safe}%") | SkillListing.description.ilike(f"%{safe}%"))
    result = await db.execute(stmt.order_by(SkillListing.created_at.desc()))
    listings = [SkillListingSummary.model_validate(r) for r in result.scalars().all()]
    await audit(None, "skill.list", resource_type="skill")
    return listings


@router.get("/my", response_model=list[SkillListingSummary])
async def my_skills(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.user)),
):
    stmt = (
        select(SkillListing)
        .where(SkillListing.submitted_by == current_user.id)
        .order_by(SkillListing.created_at.desc())
    )
    result = await db.execute(stmt)
    listings = [SkillListingSummary.model_validate(r) for r in result.scalars().all()]
    await audit(current_user, "skill.my_list", resource_type="skill")
    return listings


@router.get("/{listing_id}", response_model=SkillListingResponse)
async def get_skill(
    listing_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(optional_current_user),
):
    listing = await resolve_listing(SkillListing, listing_id, db, require_status=ListingStatus.approved)
    if listing:
        await audit(
            current_user, "skill.view", resource_type="skill", resource_id=str(listing.id), resource_name=listing.name
        )
        return SkillListingResponse.model_validate(listing)

    listing = await resolve_listing(SkillListing, listing_id, db)
    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found")

    if current_user and (
        listing.submitted_by == current_user.id
        or ROLE_HIERARCHY.get(current_user.role, 999) <= ROLE_HIERARCHY[UserRole.reviewer]
    ):
        await audit(
            current_user, "skill.view", resource_type="skill", resource_id=str(listing.id), resource_name=listing.name
        )
        return SkillListingResponse.model_validate(listing)

    raise HTTPException(status_code=404, detail="Listing not found")


@router.post("/{listing_id}/install", response_model=SkillInstallResponse)
async def install_skill(
    listing_id: str,
    req: SkillInstallRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.user)),
):
    listing = await resolve_listing(SkillListing, listing_id, db, require_status=ListingStatus.approved)
    if not listing:
        listing = await resolve_listing(SkillListing, listing_id, db)
        if not listing or listing.submitted_by != current_user.id:
            raise HTTPException(status_code=404, detail="Listing not found or not approved")

    db.add(SkillDownload(listing_id=listing.id, user_id=current_user.id, ide=req.ide))
    await db.commit()

    from api.routes.config import derive_endpoints
    from services.skill_config_generator import generate_skill_config

    endpoints = derive_endpoints(request)
    config = generate_skill_config(listing, req.ide, server_url=endpoints["api"], scope=req.scope)
    await audit(
        current_user, "skill.install", resource_type="skill", resource_id=str(listing.id), resource_name=listing.name
    )
    return SkillInstallResponse(listing_id=listing.id, ide=req.ide, config_snippet=config)


@router.post("/draft", response_model=SkillListingResponse)
async def save_skill_draft(
    req: SkillDraftRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.user)),
):
    listing = SkillListing(
        name=req.name,
        version=req.version,
        description=req.description,
        owner=req.owner or current_user.username or current_user.email,
        git_url=req.git_url,
        skill_path=req.skill_path,
        target_agents=req.target_agents,
        task_type=req.task_type,
        triggers=req.triggers,
        slash_command=req.slash_command,
        has_scripts=req.has_scripts,
        has_templates=req.has_templates,
        supported_ides=req.supported_ides,
        is_power=req.is_power,
        power_md=req.power_md,
        mcp_server_config=req.mcp_server_config,
        activation_keywords=req.activation_keywords,
        status=ListingStatus.draft,
        submitted_by=current_user.id,
        owner_org_id=current_user.org_id,
    )
    db.add(listing)
    await db.commit()
    await db.refresh(listing)
    await audit(
        current_user,
        "skill.draft.create",
        resource_type="skill",
        resource_id=str(listing.id),
        resource_name=listing.name,
    )
    return SkillListingResponse.model_validate(listing)


@router.put("/{listing_id}/draft", response_model=SkillListingResponse)
async def update_skill_draft(
    listing_id: str,
    req: SkillUpdateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.user)),
):
    listing = await resolve_listing(SkillListing, listing_id, db)
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
        "git_url",
        "skill_path",
        "target_agents",
        "task_type",
        "triggers",
        "slash_command",
        "has_scripts",
        "has_templates",
        "supported_ides",
        "is_power",
        "power_md",
        "mcp_server_config",
        "activation_keywords",
    ):
        val = getattr(req, field)
        if val is not None:
            setattr(listing, field, val)

    await db.commit()
    await db.refresh(listing)
    await audit(
        current_user,
        "skill.draft.update",
        resource_type="skill",
        resource_id=str(listing.id),
        resource_name=listing.name,
    )
    return SkillListingResponse.model_validate(listing)


@router.post("/{listing_id}/submit", response_model=SkillListingResponse)
async def submit_skill_draft(
    listing_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.user)),
):
    listing = await resolve_listing(SkillListing, listing_id, db)
    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found")
    if listing.submitted_by != current_user.id:
        raise HTTPException(status_code=403, detail="Not the listing owner")
    if listing.status not in (ListingStatus.draft, ListingStatus.rejected):
        raise HTTPException(status_code=400, detail="Listing is not a draft")

    if not listing.description:
        raise HTTPException(status_code=400, detail="Description is required before submitting")

    listing.status = ListingStatus.pending
    await db.commit()
    await db.refresh(listing)
    await audit(
        current_user,
        "skill.draft.submit",
        resource_type="skill",
        resource_id=str(listing.id),
        resource_name=listing.name,
    )
    return SkillListingResponse.model_validate(listing)


@router.delete("/{listing_id}")
async def delete_skill(
    listing_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.user)),
):
    listing = await resolve_listing(SkillListing, listing_id, db)
    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found")
    is_admin = ROLE_HIERARCHY.get(current_user.role, 999) <= ROLE_HIERARCHY[UserRole.admin]
    if listing.submitted_by != current_user.id and not is_admin:
        raise HTTPException(status_code=403, detail="Not authorized")
    if listing.status == ListingStatus.approved and not is_admin:
        raise HTTPException(status_code=400, detail="Cannot delete an approved listing. Contact an admin.")

    for r in (await db.execute(select(SkillDownload).where(SkillDownload.listing_id == listing.id))).scalars().all():
        await db.delete(r)

    listing_name = listing.name
    await db.delete(listing)
    await db.commit()
    await audit(
        current_user, "skill.delete", resource_type="skill", resource_id=str(listing_id), resource_name=listing_name
    )
    return {"deleted": str(listing_id)}
