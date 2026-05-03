import enum
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import String, cast, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import get_db, require_role, resolve_prefix_id
from api.sanitize import escape_like
from models.agent import Agent, AgentStatus, AgentVersion
from models.component_bundle import ComponentBundle
from models.hook import HookListing, HookVersion
from models.mcp import ListingStatus, McpListing, McpVersion
from models.prompt import PromptListing, PromptVersion
from models.sandbox import SandboxListing, SandboxVersion
from models.skill import SkillListing, SkillVersion
from models.user import User, UserRole
from schemas.mcp import ReviewActionRequest
from services.audit_helpers import audit
from services.editing_lock import is_actively_editing

router = APIRouter(prefix="/api/v1/review", tags=["review"])

LISTING_MODELS = {
    "mcp": McpListing,
    "skill": SkillListing,
    "hook": HookListing,
    "prompt": PromptListing,
    "sandbox": SandboxListing,
}

VERSION_MODELS = {
    "mcp": McpVersion,
    "skill": SkillVersion,
    "hook": HookVersion,
    "prompt": PromptVersion,
    "sandbox": SandboxVersion,
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


async def _check_agent_components_ready(components, db: AsyncSession) -> tuple[bool, list[dict]]:
    """Check if all of an agent version's components are approved."""
    if not components:
        return True, []

    by_type: dict[str, list[uuid.UUID]] = {}
    for comp in components:
        by_type.setdefault(comp.component_type, []).append(comp.component_id)

    blocking: list[dict] = []
    for comp_type, ids in by_type.items():
        model = LISTING_MODELS.get(comp_type)
        version_model = VERSION_MODELS.get(comp_type)
        if not model or not version_model:
            continue
        rows = (
            await db.execute(
                select(model.id, model.name, version_model.status)
                .join(version_model, model.latest_version_id == version_model.id)
                .where(model.id.in_(ids))
            )
        ).all()
        for row in rows:
            if row.status != ListingStatus.approved:
                blocking.append(
                    {
                        "component_type": comp_type,
                        "component_id": str(row.id),
                        "name": row.name,
                        "status": row.status.value,
                    }
                )
    return len(blocking) == 0, blocking


async def _query_pending_agents(db: AsyncSession) -> list[dict]:
    # Find agents that have ANY pending version (not just latest_version_id).
    # This ensures version updates appear in the review queue after the first
    # version is approved.
    pending_versions_stmt = (
        select(AgentVersion).where(AgentVersion.status == AgentStatus.pending).order_by(AgentVersion.created_at.desc())
    )
    pending_versions = (await db.execute(pending_versions_stmt)).scalars().all()

    if not pending_versions:
        return []

    # Group by agent_id, take the newest pending version per agent.
    # Skip versions that are actively being edited by their owner.
    seen_agents: dict[uuid.UUID, AgentVersion] = {}
    for v in pending_versions:
        if v.agent_id not in seen_agents and not is_actively_editing(v):
            seen_agents[v.agent_id] = v

    # Load the agents
    agent_ids = list(seen_agents.keys())
    agents_result = await db.execute(select(Agent).where(Agent.id.in_(agent_ids)))
    agents_map = {a.id: a for a in agents_result.scalars().all()}

    user_ids = {a.created_by for a in agents_map.values()}
    user_map: dict[uuid.UUID, str] = {}
    if user_ids:
        rows = await db.execute(select(User.id, User.email).where(User.id.in_(user_ids)))
        user_map = {r[0]: r[1] for r in rows.all()}

    items = []
    for agent_id, pending_ver in seen_agents.items():
        a = agents_map.get(agent_id)
        if not a:
            continue
        components_ready, blocking = await _check_agent_components_ready(pending_ver.components, db)
        items.append(
            {
                "type": "agent",
                "id": str(a.id),
                "name": a.name,
                "description": pending_ver.description or a.description or "",
                "version": pending_ver.version,
                "owner": a.owner or "",
                "status": pending_ver.status.value,
                "submitted_by": user_map.get(a.created_by, str(a.created_by)),
                "created_at": pending_ver.created_at.isoformat() if pending_ver.created_at else "",
                "component_count": len(pending_ver.components) if pending_ver.components else 0,
                "components_ready": components_ready,
                "blocking_components": blocking,
            }
        )
    return items


async def _query_pending_components(db: AsyncSession, type_filter: str | None = None) -> list[dict]:
    models_to_query = (
        {type_filter: LISTING_MODELS[type_filter]} if type_filter and type_filter in LISTING_MODELS else LISTING_MODELS
    )
    items = []
    user_ids: set[uuid.UUID] = set()
    for listing_type, model in models_to_query.items():
        version_model = VERSION_MODELS[listing_type]
        # Find listings that have ANY pending version (not just latest_version_id).
        # This ensures version updates appear in the queue after first approval.
        pending_versions_stmt = (
            select(version_model)
            .where(version_model.status == ListingStatus.pending)
            .order_by(version_model.released_at.desc())
        )
        pending_versions = (await db.execute(pending_versions_stmt)).scalars().all()
        if not pending_versions:
            continue

        # Group by listing_id, take newest pending version per listing
        seen_listings: dict[uuid.UUID, object] = {}
        for pv in pending_versions:
            if pv.listing_id not in seen_listings and not is_actively_editing(pv):
                seen_listings[pv.listing_id] = pv

        if not seen_listings:
            continue

        # Load the listings
        listings_result = await db.execute(select(model).where(model.id.in_(list(seen_listings.keys()))))
        listings_map = {r.id: r for r in listings_result.scalars().all()}

        for listing_id, pv in seen_listings.items():
            r = listings_map.get(listing_id)
            if not r:
                continue
            user_ids.add(r.submitted_by)
            item: dict = {
                "type": listing_type,
                "id": str(r.id),
                "name": r.name,
                "description": getattr(pv, "description", None) or getattr(r, "description", None) or "",
                "version": getattr(pv, "version", None) or "",
                "owner": getattr(r, "owner", None) or "",
                "status": pv.status.value,
                "submitted_by": r.submitted_by,
                "created_at": pv.created_at.isoformat()
                if hasattr(pv, "created_at") and pv.created_at
                else r.created_at.isoformat(),
                "bundle_id": str(r.bundle_id) if isinstance(getattr(r, "bundle_id", None), uuid.UUID) else None,
            }
            # Include validation results for MCP listings
            if listing_type == "mcp" and hasattr(r, "validation_results"):
                item["mcp_validated"] = getattr(r, "mcp_validated", False)
                item["validation_results"] = [
                    {
                        "stage": vr.stage,
                        "passed": vr.passed,
                        "details": vr.details,
                        "run_at": vr.run_at.isoformat() if vr.run_at else None,
                    }
                    for vr in r.validation_results
                ]
            items.append(item)

    # Resolve bundle names
    bundle_ids = {i["bundle_id"] for i in items if i.get("bundle_id")}
    bundle_map: dict[str, str] = {}
    if bundle_ids:
        brows = await db.execute(
            select(ComponentBundle.id, ComponentBundle.name).where(
                ComponentBundle.id.in_([uuid.UUID(b) for b in bundle_ids])
            )
        )
        bundle_map = {str(r[0]): r[1] for r in brows.all()}
    for item in items:
        if item.get("bundle_id"):
            item["bundle_name"] = bundle_map.get(item["bundle_id"], "")

    # Resolve user UUIDs to display names
    user_map: dict[uuid.UUID, str] = {}
    if user_ids:
        result = await db.execute(select(User).where(User.id.in_(user_ids)))
        for u in result.scalars().all():
            user_map[u.id] = u.name or u.email

    for item in items:
        uid = item["submitted_by"]
        item["submitted_by"] = user_map.get(uid, str(uid))

    return items


@router.get("")
async def list_pending(
    type: str | None = Query(None),
    tab: str | None = Query(
        None,
        description="Filter by type: 'agents' or 'components'. Defaults to all pending items.",
    ),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.reviewer)),
):
    if tab == "agents":
        result = await _query_pending_agents(db)
        await audit(current_user, "review.list", detail="tab=agents")
        return result

    if tab == "components":
        result = await _query_pending_components(db, type)
        await audit(current_user, "review.list", detail=f"tab=components type={type}")
        return result

    # Default: return both agents and components
    agents = await _query_pending_agents(db)
    components = await _query_pending_components(db, type)

    # Merge and sort by created_at (most recent first)
    all_items = agents + components
    all_items.sort(key=lambda x: x["created_at"], reverse=True)

    await audit(current_user, "review.list", detail=f"type={type}")
    return all_items


_DETAIL_FIELDS: dict[str, list[str]] = {
    "mcp": [
        "git_url",
        "git_ref",
        "category",
        "transport",
        "framework",
        "docker_image",
        "command",
        "args",
        "url",
        "headers",
        "auto_approve",
        "tools_schema",
        "environment_variables",
        "supported_ides",
        "setup_instructions",
        "changelog",
        "rejection_reason",
        "bundle_id",
    ],
    "skill": [
        "git_url",
        "git_ref",
        "skill_path",
        "target_agents",
        "task_type",
        "triggers",
        "slash_command",
        "has_scripts",
        "has_templates",
        "is_power",
        "power_md",
        "mcp_server_config",
        "activation_keywords",
        "supported_ides",
        "rejection_reason",
        "bundle_id",
    ],
    "hook": [
        "git_url",
        "git_ref",
        "event",
        "execution_mode",
        "priority",
        "handler_type",
        "handler_config",
        "input_schema",
        "output_schema",
        "scope",
        "tool_filter",
        "file_pattern",
        "supported_ides",
        "rejection_reason",
        "bundle_id",
    ],
    "prompt": [
        "git_url",
        "git_ref",
        "category",
        "template",
        "variables",
        "model_hints",
        "tags",
        "supported_ides",
        "rejection_reason",
        "bundle_id",
    ],
    "sandbox": [
        "git_url",
        "git_ref",
        "runtime_type",
        "image",
        "dockerfile_url",
        "resource_limits",
        "network_policy",
        "allowed_mounts",
        "env_vars",
        "entrypoint",
        "supported_ides",
        "rejection_reason",
        "bundle_id",
    ],
}


def _safe_serialize(val: object) -> object:
    if isinstance(val, uuid.UUID):
        return str(val)
    if hasattr(val, "isoformat"):
        return val.isoformat()
    if isinstance(val, enum.Enum):
        return val.value
    return val


def _serialize_listing_detail(listing_type: str, listing) -> dict:
    # Find the pending version if one exists (for reviews, we want pending content)
    pending_ver = None
    if hasattr(listing, "versions"):
        pending_ver = next(
            (v for v in listing.versions if v.status == ListingStatus.pending),
            None,
        )
    # Use the pending version for field resolution; fall back to listing properties
    source = pending_ver if pending_ver else listing

    base = {
        "type": listing_type,
        "id": str(listing.id),
        "name": listing.name,
        "description": getattr(source, "description", None) or "",
        "version": getattr(source, "version", None) or "",
        "owner": getattr(listing, "owner", None) or "",
        "status": source.status.value if hasattr(source, "status") else listing.status.value,
        "submitted_by": str(listing.submitted_by),
        "created_at": listing.created_at.isoformat(),
        "updated_at": listing.updated_at.isoformat() if getattr(listing, "updated_at", None) else None,
    }
    for field in _DETAIL_FIELDS.get(listing_type, []):
        val = getattr(source, field, None)
        if val is None:
            val = getattr(listing, field, None)
        base[field] = _safe_serialize(val)
    if listing_type == "mcp" and hasattr(listing, "validation_results"):
        base["mcp_validated"] = getattr(listing, "mcp_validated", False)
        base["validation_results"] = [
            {
                "stage": vr.stage,
                "passed": vr.passed,
                "details": vr.details,
                "run_at": vr.run_at.isoformat() if vr.run_at else None,
            }
            for vr in listing.validation_results
        ]
    return base


@router.get("/{listing_id}")
async def get_review(
    listing_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.reviewer)),
):
    listing_type, listing = await _find_listing(listing_id, db)

    if listing:
        result = _serialize_listing_detail(listing_type, listing)
    else:
        # Fallback: check Agent table
        try:
            agent_uuid = uuid.UUID(listing_id)
        except ValueError:
            raise HTTPException(status_code=404, detail="Listing not found")
        agent = (await db.execute(select(Agent).where(Agent.id == agent_uuid))).scalar_one_or_none()
        if not agent:
            raise HTTPException(status_code=404, detail="Listing not found")
        # Use the pending version for review (not latest_version which is the approved one)
        pending_ver = next(
            (v for v in agent.versions if v.status == AgentStatus.pending),
            None,
        )
        ver = pending_ver or agent.latest_version
        ver_components = ver.components if ver else agent.components
        components_ready, blocking = await _check_agent_components_ready(ver_components, db)
        result = {
            "type": "agent",
            "id": str(agent.id),
            "name": agent.name,
            "description": (ver.description if ver else "") or agent.description or "",
            "version": (ver.version if ver else "") or agent.version or "",
            "owner": agent.owner or "",
            "status": (ver.status.value if ver else agent.status.value),
            "submitted_by": str(agent.created_by),
            "created_at": agent.created_at.isoformat() if agent.created_at else None,
            "updated_at": agent.updated_at.isoformat() if agent.updated_at else None,
            "git_url": getattr(agent, "git_url", None),
            "prompt": (ver.prompt if ver else "") or "",
            "model_name": (ver.model_name if ver else "") or "",
            "model_config_json": (ver.model_config_json if ver else {}) or {},
            "external_mcps": (ver.external_mcps if ver else []) or [],
            "supported_ides": (ver.supported_ides if ver else []) or [],
            "required_ide_features": (ver.required_ide_features if ver else []) or [],
            "rejection_reason": ver.rejection_reason if ver else None,
            "component_count": len(ver_components),
            "components_ready": components_ready,
            "component_blockers": blocking,
            "components": [
                {
                    "component_type": c.component_type,
                    "component_id": str(c.component_id),
                }
                for c in ver_components
            ],
        }

        # Expand component details with resolved listing content
        expanded_components = []
        for c in ver_components:
            comp_data = {
                "component_type": c.component_type,
                "component_id": str(c.component_id),
                "name": getattr(c, "component_name", "") or "",
            }
            model = LISTING_MODELS.get(c.component_type)
            if model:
                listing = (await db.execute(select(model).where(model.id == c.component_id))).scalar_one_or_none()
                if listing:
                    comp_data["name"] = listing.name
                    if c.component_type == "prompt":
                        comp_data["template"] = getattr(listing, "template", "") or ""
                        comp_data["category"] = getattr(listing, "category", "") or ""
                    else:
                        comp_data["description"] = getattr(listing, "description", "") or ""
            expanded_components.append(comp_data)
        result["components"] = expanded_components

    # Resolve submitted_by UUID to display name
    uid_str = result.get("submitted_by", "")
    try:
        uid = uuid.UUID(uid_str)
        user = (await db.execute(select(User).where(User.id == uid))).scalar_one_or_none()
        if user:
            result["submitted_by"] = user.name or user.email
    except (ValueError, AttributeError):
        pass

    await audit(
        current_user,
        "review.view",
        resource_type=result.get("type", ""),
        resource_id=result.get("id", ""),
        resource_name=result.get("name", ""),
    )
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

    # Find the pending version to approve (may not be latest_version)
    pending_ver = None
    if hasattr(listing, "versions"):
        pending_ver = next(
            (v for v in listing.versions if v.status == ListingStatus.pending),
            None,
        )

    if pending_ver:
        if is_actively_editing(pending_ver):
            raise HTTPException(status_code=409, detail="Cannot approve: the owner is currently editing this item")
        pending_ver.status = ListingStatus.approved
        pending_ver.rejection_reason = None
        pending_ver.reviewed_by = current_user.id
        pending_ver.reviewed_at = datetime.now(UTC)
        # Flush version changes first to avoid CircularDependencyError
        await db.flush()
        # Update latest_version_id to point to newly approved version
        listing.latest_version_id = pending_ver.id
    else:
        # Fallback: legacy path for listings without versioning
        if listing.latest_version and is_actively_editing(listing.latest_version):
            raise HTTPException(status_code=409, detail="Cannot approve: the owner is currently editing this item")
        listing.status = ListingStatus.approved
        listing.rejection_reason = None

    await db.commit()
    await db.refresh(listing)
    await audit(
        current_user,
        "review.approve",
        resource_type="listing",
        resource_id=str(listing.id),
        resource_name=listing.name,
        detail=f"listing_type={listing_type}",
    )
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

    # Find the pending version to reject (may not be latest_version)
    pending_ver = None
    if hasattr(listing, "versions"):
        pending_ver = next(
            (v for v in listing.versions if v.status == ListingStatus.pending),
            None,
        )

    if pending_ver:
        if is_actively_editing(pending_ver):
            raise HTTPException(status_code=409, detail="Cannot reject: the owner is currently editing this item")
        pending_ver.status = ListingStatus.rejected
        pending_ver.rejection_reason = req.reason
        pending_ver.reviewed_by = current_user.id
        pending_ver.reviewed_at = datetime.now(UTC)
    else:
        # Fallback: legacy path for listings without versioning
        if listing.latest_version and is_actively_editing(listing.latest_version):
            raise HTTPException(status_code=409, detail="Cannot reject: the owner is currently editing this item")
        listing.status = ListingStatus.rejected
        listing.rejection_reason = req.reason

    await db.commit()
    await db.refresh(listing)
    await audit(
        current_user,
        "review.reject",
        resource_type="listing",
        resource_id=str(listing.id),
        resource_name=listing.name,
        detail=f"listing_type={listing_type} reason={req.reason}",
    )
    return {"type": listing_type, "id": str(listing.id), "name": listing.name, "status": listing.status.value}


# ---------------------------------------------------------------------------
# Agent review
# ---------------------------------------------------------------------------


class AgentRejectRequest(BaseModel):
    reason: str


@router.post("/agents/{agent_id}/approve")
async def approve_agent(
    agent_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.reviewer)),
):
    from services.versioning import parse_semver

    agent = (await db.execute(select(Agent).where(Agent.id == agent_id))).scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    pending_versions = (
        (
            await db.execute(
                select(AgentVersion)
                .where(AgentVersion.agent_id == agent.id, AgentVersion.status == AgentStatus.pending)
                .order_by(AgentVersion.created_at.desc())
            )
        )
        .scalars()
        .all()
    )

    if not pending_versions:
        raise HTTPException(status_code=400, detail=f"Agent has no pending versions (latest is '{agent.status.value}')")

    for pv in pending_versions:
        if is_actively_editing(pv):
            raise HTTPException(status_code=409, detail="Cannot approve: the owner is currently editing this agent")

    newest_pending = pending_versions[0]
    components_ready, blocking = await _check_agent_components_ready(newest_pending.components, db)
    if not components_ready:
        raise HTTPException(
            status_code=422,
            detail={
                "message": "Cannot approve: some components are not approved yet",
                "blocking_components": blocking,
            },
        )

    now = datetime.now(UTC)
    # Approve only the newest pending version; mark older ones as superseded
    newest_pending.status = AgentStatus.approved
    newest_pending.rejection_reason = None
    newest_pending.reviewed_by = current_user.id
    newest_pending.reviewed_at = now
    for pv in pending_versions[1:]:
        pv.status = AgentStatus.rejected
        pv.rejection_reason = "Superseded by newer version"
        pv.reviewed_by = current_user.id
        pv.reviewed_at = now

    # Flush version changes first to avoid CircularDependencyError
    await db.flush()

    current_latest = agent.latest_version
    new_parsed = parse_semver(newest_pending.version)
    current_parsed = parse_semver(current_latest.version) if current_latest else None
    if not current_latest or (new_parsed is not None and current_parsed is not None and new_parsed >= current_parsed):
        agent.latest_version_id = newest_pending.id

    await db.commit()
    await audit(
        current_user,
        "review.agent.approve",
        resource_type="agent",
        resource_id=str(agent_id),
        resource_name=agent.name,
    )
    return {"id": str(agent.id), "name": agent.name, "status": "approved", "version": newest_pending.version}


@router.post("/agents/{agent_id}/reject")
async def reject_agent(
    agent_id: uuid.UUID,
    req: AgentRejectRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.reviewer)),
):
    agent = (await db.execute(select(Agent).where(Agent.id == agent_id))).scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    pending_versions = (
        (
            await db.execute(
                select(AgentVersion)
                .where(AgentVersion.agent_id == agent.id, AgentVersion.status == AgentStatus.pending)
                .order_by(AgentVersion.created_at.desc())
            )
        )
        .scalars()
        .all()
    )

    if not pending_versions:
        raise HTTPException(status_code=400, detail=f"Agent has no pending versions (latest is '{agent.status.value}')")
    else:
        for pv in pending_versions:
            if is_actively_editing(pv):
                raise HTTPException(status_code=409, detail="Cannot reject: the owner is currently editing this agent")
        now = datetime.now(UTC)
        for pv in pending_versions:
            pv.status = AgentStatus.rejected
            pv.rejection_reason = req.reason
            pv.reviewed_by = current_user.id
            pv.reviewed_at = now
        await db.flush()

    await db.commit()
    await audit(
        current_user,
        "review.agent.reject",
        resource_type="agent",
        resource_id=str(agent_id),
        resource_name=agent.name,
        detail=f"reason={req.reason}",
    )
    rejected_version = pending_versions[0].version if pending_versions else ""
    return {"id": str(agent.id), "name": agent.name, "status": "rejected", "version": rejected_version}


# ---------------------------------------------------------------------------
# Bundle review (atomic approve/reject)
# ---------------------------------------------------------------------------


@router.post("/bundles/{bundle_id}/approve")
async def approve_bundle(
    bundle_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.reviewer)),
):
    bundle = (await db.execute(select(ComponentBundle).where(ComponentBundle.id == bundle_id))).scalar_one_or_none()
    if not bundle:
        raise HTTPException(status_code=404, detail="Bundle not found")

    count = 0
    for model in LISTING_MODELS.values():
        result = await db.execute(select(model).where(model.bundle_id == bundle_id))
        for listing in result.scalars().all():
            if listing.latest_version and is_actively_editing(listing.latest_version):
                raise HTTPException(
                    status_code=409,
                    detail=f"Cannot approve: '{listing.name}' is currently being edited by its owner",
                )
            listing.status = ListingStatus.approved
            listing.rejection_reason = None
            count += 1

    await db.commit()
    await audit(
        current_user,
        "review.bundle.approve",
        resource_type="bundle",
        resource_id=str(bundle_id),
        resource_name=bundle.name,
        detail=f"approved_count={count}",
    )
    return {"bundle_id": str(bundle_id), "name": bundle.name, "approved_count": count}


@router.post("/bundles/{bundle_id}/reject")
async def reject_bundle(
    bundle_id: uuid.UUID,
    req: ReviewActionRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.reviewer)),
):
    bundle = (await db.execute(select(ComponentBundle).where(ComponentBundle.id == bundle_id))).scalar_one_or_none()
    if not bundle:
        raise HTTPException(status_code=404, detail="Bundle not found")

    count = 0
    for model in LISTING_MODELS.values():
        result = await db.execute(select(model).where(model.bundle_id == bundle_id))
        for listing in result.scalars().all():
            if listing.latest_version and is_actively_editing(listing.latest_version):
                raise HTTPException(
                    status_code=409,
                    detail=f"Cannot reject: '{listing.name}' is currently being edited by its owner",
                )
            listing.status = ListingStatus.rejected
            listing.rejection_reason = req.reason
            count += 1

    await db.commit()
    await audit(
        current_user,
        "review.bundle.reject",
        resource_type="bundle",
        resource_id=str(bundle_id),
        resource_name=bundle.name,
        detail=f"rejected_count={count} reason={req.reason}",
    )
    return {"bundle_id": str(bundle_id), "name": bundle.name, "rejected_count": count}


# ---------------------------------------------------------------------------
# Smart bulk approve: MCP + related skills
# ---------------------------------------------------------------------------


@router.get("/{listing_id}/related-skills")
async def get_related_skills(
    listing_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.reviewer)),
):
    listing_type, listing = await _find_listing(listing_id, db)
    if not listing or listing_type != "mcp":
        return {"skills": []}

    mcp_name = listing.name
    mcp_id = str(listing.id)

    stmt = (
        select(SkillListing)
        .join(SkillVersion, SkillListing.latest_version_id == SkillVersion.id)
        .where(
            SkillVersion.status == ListingStatus.pending,
            SkillVersion.mcp_server_config.isnot(None),
            or_(
                cast(SkillVersion.mcp_server_config, String).contains(escape_like(mcp_name)),
                cast(SkillVersion.mcp_server_config, String).contains(escape_like(mcp_id)),
            ),
        )
        .order_by(SkillListing.created_at.desc())
    )
    skills = (await db.execute(stmt)).scalars().all()

    user_ids = {s.submitted_by for s in skills}
    user_map: dict[uuid.UUID, str] = {}
    if user_ids:
        rows = await db.execute(select(User).where(User.id.in_(user_ids)))
        for u in rows.scalars().all():
            user_map[u.id] = u.name or u.email

    result = {
        "skills": [
            {
                "id": str(s.id),
                "type": "skill",
                "name": s.name,
                "version": s.version or "",
                "description": s.description or "",
                "task_type": s.task_type,
                "target_agents": s.target_agents or [],
                "mcp_server_config": s.mcp_server_config,
                "status": s.status.value,
                "submitted_by": user_map.get(s.submitted_by, str(s.submitted_by)),
                "created_at": s.created_at.isoformat(),
            }
            for s in skills
        ]
    }
    await audit(
        current_user,
        "review.related_skills",
        resource_type="listing",
        resource_id=str(listing.id) if listing else listing_id,
        resource_name=mcp_name if listing else "",
        detail=f"skill_count={len(skills)}",
    )
    return result


class McpBulkApproveRequest(BaseModel):
    skill_ids: list[str] = []


@router.post("/{listing_id}/approve-with-skills")
async def approve_mcp_with_skills(
    listing_id: str,
    req: McpBulkApproveRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.reviewer)),
):
    listing_type, listing = await _find_listing(listing_id, db)
    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found")
    if listing_type != "mcp":
        raise HTTPException(status_code=400, detail="Only MCP listings support bulk skill approve")

    listing.status = ListingStatus.approved
    listing.rejection_reason = None

    approved_skill_ids: list[str] = []
    for sid in req.skill_ids:
        try:
            skill_uuid = uuid.UUID(sid)
        except ValueError:
            continue
        skill = (await db.execute(select(SkillListing).where(SkillListing.id == skill_uuid))).scalar_one_or_none()
        if skill and skill.status == ListingStatus.pending:
            skill.status = ListingStatus.approved
            skill.rejection_reason = None
            approved_skill_ids.append(str(skill.id))

    await db.commit()
    await db.refresh(listing)
    await audit(
        current_user,
        "review.approve_with_skills",
        resource_type="listing",
        resource_id=str(listing.id),
        resource_name=listing.name,
        detail=f"listing_type={listing_type} approved_skills={len(approved_skill_ids)} skill_ids={approved_skill_ids}",
    )
    return {
        "mcp": {"id": str(listing.id), "name": listing.name, "status": listing.status.value},
        "approved_skills": len(approved_skill_ids),
        "skill_ids": approved_skill_ids,
    }
