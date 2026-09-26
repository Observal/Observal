# SPDX-FileCopyrightText: 2026 Aryan Iyappan <aryaniyappan2006@gmail.com>
# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""Agent composition resolver - looks up and validates all components for an agent."""

import uuid
from typing import Literal

from loguru import logger as optic
from pydantic import BaseModel, Field, computed_field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import apply_publish_scope, apply_visibility_filter
from models.agent import Agent, AgentVersion
from models.hook import HookListing, HookVersion
from models.mcp import ListingStatus, McpListing, McpVersion
from models.prompt import PromptListing, PromptVersion
from models.sandbox import SandboxListing, SandboxVersion
from models.skill import SkillListing, SkillVersion
from services.shared.utils import registry_item_slug

ComponentType = Literal["mcp", "skill", "hook", "prompt", "sandbox"]

# Maps component_type string to its ORM model
_LISTING_MODELS: dict[str, type] = {
    "mcp": McpListing,
    "skill": SkillListing,
    "hook": HookListing,
    "prompt": PromptListing,
    "sandbox": SandboxListing,
}

_VERSION_MODELS: dict[str, type] = {
    "mcp": McpVersion,
    "skill": SkillVersion,
    "hook": HookVersion,
    "prompt": PromptVersion,
    "sandbox": SandboxVersion,
}


class _VersionedListing:
    """Proxy around a component listing that overrides version-dependent properties
    with a specific pinned version while preserving listing-level identity attributes.
    """

    _listing_identity_attrs = {
        "id",
        "name",
        "namespace",
        "slug",
        "category",
        "owner",
        "team_id",
        "is_private",
        "bundle_id",
        "submitted_by",
        "co_authors",
        "created_at",
        "updated_at",
        "validation_results",
        "versions",
        "qualified_name",
        "visibility",
    }

    def __init__(self, listing, version):
        self._listing = listing
        self._version = version

    def __getattr__(self, name):
        if name == "latest_version":
            return self._version
        if name in self._listing_identity_attrs:
            return getattr(self._listing, name)
        if hasattr(self._version, name):
            return getattr(self._version, name)
        return getattr(self._listing, name)


class ResolvedComponent(BaseModel):
    """A fully resolved component with its listing data."""

    model_config = {"frozen": True}

    component_type: ComponentType
    component_id: uuid.UUID
    name: str
    version: str
    git_url: str | None = None
    git_ref: str | None = None
    description: str = ""
    order_index: int = 0
    config_override: dict | None = None
    listing_status: str = ""
    extra: dict = Field(default_factory=dict)


class ResolutionError(BaseModel):
    """A single resolution failure."""

    model_config = {"frozen": True}

    component_type: str
    component_id: uuid.UUID
    reason: str


class ResolvedAgent(BaseModel):
    """Complete resolution result for an agent."""

    agent_id: uuid.UUID
    agent_name: str
    agent_version: str
    agent_prompt: str = ""
    agent_description: str = ""
    model_name: str = ""
    models_by_harness: dict[str, str] = Field(default_factory=dict)
    components: list[ResolvedComponent] = Field(default_factory=list)
    errors: list[ResolutionError] = Field(default_factory=list)

    @computed_field
    @property
    def ok(self) -> bool:

        return len(self.errors) == 0

    def components_by_type(self, component_type: str) -> list[ResolvedComponent]:
        optic.trace("filtering components by type {} ({} total)", component_type, len(self.components))
        return [c for c in self.components if c.component_type == component_type]


def _extract_extra(listing, component_type: str) -> dict:
    """Pull type-specific fields from a listing into a flat dict for downstream use."""
    optic.trace("extracting {} metadata from listing", component_type)
    if component_type == "mcp":
        return {
            "transport": getattr(listing, "transport", None),
            "tools_schema": getattr(listing, "tools_schema", None),
            "mcp_validated": getattr(listing, "mcp_validated", False),
            "setup_instructions": getattr(listing, "setup_instructions", None),
        }
    if component_type == "skill":
        return {
            "skill_path": getattr(listing, "skill_path", "/"),
            "task_type": getattr(listing, "task_type", ""),
            "slash_command": getattr(listing, "slash_command", None),
            "skill_md_content": getattr(listing, "skill_md_content", None),
        }
    if component_type == "hook":
        extra = {
            "event": getattr(listing, "event", ""),
            "execution_mode": getattr(listing, "execution_mode", "async"),
            "priority": getattr(listing, "priority", 100),
            "handler_type": getattr(listing, "handler_type", ""),
            "handler_config": getattr(listing, "handler_config", {}),
            "scope": getattr(listing, "scope", "agent"),
        }
        if getattr(listing, "source_url", None):
            extra["source_url"] = listing.source_url
            extra["source_ref"] = getattr(listing, "source_ref", None)
            extra["resolved_sha"] = getattr(listing, "resolved_sha", None)
        if getattr(listing, "script_filename", None):
            extra["script_filename"] = listing.script_filename
        if getattr(listing, "requirements", None):
            extra["requirements"] = listing.requirements
        return extra
    if component_type == "prompt":
        return {
            "template": getattr(listing, "template", ""),
            "variables": getattr(listing, "variables", []),
            "category": getattr(listing, "category", ""),
        }
    if component_type == "sandbox":
        extra = {
            "runtime_type": getattr(listing, "runtime_type", ""),
            "image": getattr(listing, "image", ""),
            "resource_limits": getattr(listing, "resource_limits", {}),
            "network_policy": getattr(listing, "network_policy", "none"),
            "entrypoint": getattr(listing, "entrypoint", None),
            "runtime_config": getattr(listing, "runtime_config", {}),
        }
        if getattr(listing, "sandbox_path", None):
            extra["sandbox_path"] = listing.sandbox_path
        return extra
    return {}


async def resolve_agent(
    agent: Agent,
    db: AsyncSession,
    *,
    require_approved: bool = True,
    current_user=None,
    target_version: AgentVersion | None = None,
) -> ResolvedAgent:
    """Resolve all components for an agent.

    Looks up each AgentComponent's listing in the correct table,
    validates status, and returns a ResolvedAgent with full details.

    Components are batched by type so each type requires at most one
    SELECT ... WHERE id IN (...) query, regardless of how many components
    of that type exist.
    """
    optic.debug("resolving agent components (require_approved={})", require_approved)
    components: list[ResolvedComponent] = []
    errors: list[ResolutionError] = []

    comps_list = list(target_version.components if target_version is not None else (agent.components or []))

    # Group components by type for batched lookups (max 5 queries total)
    by_type: dict[str, list] = {}
    for comp in comps_list:
        model = _LISTING_MODELS.get(comp.component_type)
        if model is None:
            errors.append(
                ResolutionError(
                    component_type=comp.component_type,
                    component_id=comp.component_id,
                    reason=f"Unknown component type: {comp.component_type}",
                )
            )
            continue
        by_type.setdefault(comp.component_type, []).append(comp)

    # Fetch all listings per type in one query each
    found: dict[uuid.UUID, object] = {}
    for comp_type, comps in by_type.items():
        model = _LISTING_MODELS[comp_type]
        ids = [c.component_id for c in comps]
        stmt = select(model).where(model.id.in_(ids))
        if current_user is not None:
            stmt = apply_visibility_filter(stmt, model, current_user)
        stmt = apply_publish_scope(stmt, model, agent.team_id if agent.is_private else None)
        result = await db.execute(stmt)
        for listing in result.scalars().all():
            found[listing.id] = listing

    # Process in original order to preserve deterministic output
    for comp in comps_list:
        if comp.component_type not in _LISTING_MODELS:
            continue  # Already recorded as error above

        listing = found.get(comp.component_id)
        if listing is None:
            errors.append(
                ResolutionError(
                    component_type=comp.component_type,
                    component_id=comp.component_id,
                    reason=f"{comp.component_type} listing {comp.component_id} not found",
                )
            )
            continue

        resolved_version = getattr(comp, "resolved_version", None)
        effective_listing = listing

        if (
            isinstance(resolved_version, str)
            and resolved_version
            and resolved_version != "latest"
            and resolved_version != getattr(listing, "version", None)
        ):
            vmodel = _VERSION_MODELS.get(comp.component_type)

            pinned = None
            if vmodel is not None:
                pinned = (
                    await db.execute(
                        select(vmodel).where(
                            vmodel.listing_id == comp.component_id,
                            vmodel.version == resolved_version,
                        )
                    )
                ).scalar_one_or_none()
            if not pinned:
                errors.append(
                    ResolutionError(
                        component_type=comp.component_type,
                        component_id=comp.component_id,
                        reason=f"{comp.component_type} '{listing.name}' version '{resolved_version}' not found",
                    )
                )
                continue
            effective_listing = _VersionedListing(listing, pinned)

        effective_status = getattr(effective_listing, "status", None)
        if require_approved and effective_status != ListingStatus.approved:
            status_str = effective_status.value if hasattr(effective_status, "value") else str(effective_status)
            ver_label = f" version '{resolved_version}'" if resolved_version and resolved_version != "latest" else ""
            errors.append(
                ResolutionError(
                    component_type=comp.component_type,
                    component_id=comp.component_id,
                    reason=f"{comp.component_type} '{listing.name}'{ver_label} is not approved (status: {status_str})",
                )
            )
            continue

        components.append(
            ResolvedComponent(
                component_type=comp.component_type,
                component_id=comp.component_id,
                name=registry_item_slug(effective_listing),
                version=getattr(effective_listing, "version", "latest"),
                git_url=getattr(effective_listing, "git_url", None),
                git_ref=getattr(effective_listing, "git_ref", None),
                description=getattr(effective_listing, "description", "") or "",
                order_index=comp.order_index,
                config_override=comp.config_override,
                listing_status=effective_status.value if hasattr(effective_status, "value") else str(effective_status),
                extra=_extract_extra(effective_listing, comp.component_type),
            )
        )

    if target_version is not None:
        agent_version_str = target_version.version
        agent_prompt_str = target_version.prompt or ""
        agent_desc_str = target_version.description or ""
        agent_model_str = target_version.model_name or ""
        raw_models_by_harness = getattr(target_version, "models_by_harness", None)
    else:
        agent_version_str = agent.version
        agent_prompt_str = agent.prompt or ""
        agent_desc_str = agent.description or ""
        agent_model_str = agent.model_name or ""
        raw_models_by_harness = getattr(agent, "models_by_harness", None)

    models_by_harness = raw_models_by_harness if isinstance(raw_models_by_harness, dict) else {}
    return ResolvedAgent(
        agent_id=agent.id,
        agent_name=registry_item_slug(agent),
        agent_version=agent_version_str,
        agent_prompt=agent_prompt_str,
        agent_description=agent_desc_str,
        model_name=agent_model_str,
        models_by_harness=models_by_harness,
        components=components,
        errors=errors,
    )


async def resolve_component_versions(components: list, db: AsyncSession) -> dict[tuple[str, uuid.UUID], str]:
    """Resolve component refs to their pinned version string."""
    by_type: dict[str, list[uuid.UUID]] = {}
    comp_requested_versions: dict[tuple[str, uuid.UUID], str] = {}
    for comp in components:
        ctype = getattr(comp, "component_type", None) or (
            comp.get("component_type") if isinstance(comp, dict) else None
        )
        cid = getattr(comp, "component_id", None) or (comp.get("component_id") if isinstance(comp, dict) else None)
        cver = getattr(comp, "version", None) or (comp.get("version") if isinstance(comp, dict) else None)
        if ctype in _LISTING_MODELS and cid is not None:
            cid = uuid.UUID(str(cid))
            by_type.setdefault(ctype, []).append(cid)
            if cver and cver != "latest":
                comp_requested_versions[(ctype, cid)] = str(cver)

    versions: dict[tuple[str, uuid.UUID], str] = {}
    for comp_type, ids in by_type.items():
        model = _LISTING_MODELS[comp_type]
        vmodel = _VERSION_MODELS[comp_type]
        rows = (await db.execute(select(model).where(model.id.in_(ids)))).scalars().all()
        for listing in rows:
            req_ver = comp_requested_versions.get((comp_type, listing.id))
            if req_ver:
                if req_ver == listing.version:
                    versions[(comp_type, listing.id)] = req_ver
                else:
                    exists = (
                        await db.execute(
                            select(vmodel.version).where(
                                vmodel.listing_id == listing.id,
                                vmodel.version == req_ver,
                            )
                        )
                    ).scalar_one_or_none()
                    versions[(comp_type, listing.id)] = exists if exists else listing.version
            else:
                versions[(comp_type, listing.id)] = listing.version
    return versions


async def validate_component_ids(
    components: list[dict],
    db: AsyncSession,
    *,
    require_approved: bool = True,
    current_user=None,
    target_team_id: uuid.UUID | None = None,
    enforce_target: bool = False,
) -> list[ResolutionError]:
    """Validate a list of component references before attaching them to an agent.

    Each dict or ComponentRef should have 'component_type' and 'component_id' keys/attrs.
    Returns a list of errors (empty if all valid).
    """
    optic.debug("validating {} component references", len(components))
    errors = []
    for ref in components:
        ctype = ref.get("component_type", "") if isinstance(ref, dict) else getattr(ref, "component_type", "")
        cid = ref.get("component_id") if isinstance(ref, dict) else getattr(ref, "component_id", None)
        cver = ref.get("version") if isinstance(ref, dict) else getattr(ref, "version", None)
        if cid is None:
            errors.append(
                ResolutionError(
                    component_type=ctype,
                    component_id=uuid.UUID(int=0),
                    reason=f"Missing component_id for {ctype}",
                )
            )
            continue

        model = _LISTING_MODELS.get(ctype)
        if model is None:
            errors.append(
                ResolutionError(
                    component_type=ctype,
                    component_id=cid,
                    reason=f"Unknown component type: {ctype}",
                )
            )
            continue

        stmt = select(model).where(model.id == cid)
        if current_user is not None:
            stmt = apply_visibility_filter(stmt, model, current_user)
        if enforce_target:
            stmt = apply_publish_scope(stmt, model, target_team_id)
        listing = (await db.execute(stmt)).scalar_one_or_none()

        if listing is None:
            errors.append(
                ResolutionError(
                    component_type=ctype,
                    component_id=cid,
                    reason=f"{ctype} listing {cid} not found",
                )
            )
            continue

        if isinstance(cver, str) and cver and cver != "latest" and cver != getattr(listing, "version", None):
            vmodel = _VERSION_MODELS.get(ctype)

            ver_row = None
            if vmodel is not None:
                ver_row = (
                    await db.execute(
                        select(vmodel).where(
                            vmodel.listing_id == cid,
                            vmodel.version == cver,
                        )
                    )
                ).scalar_one_or_none()
            if ver_row is None:
                errors.append(
                    ResolutionError(
                        component_type=ctype,
                        component_id=cid,
                        reason=f"{ctype} '{listing.name}' version '{cver}' not found",
                    )
                )
                continue
            if require_approved and getattr(ver_row, "status", None) != ListingStatus.approved:
                status_val = getattr(ver_row, "status", None)
                status_str = status_val.value if hasattr(status_val, "value") else str(status_val)
                errors.append(
                    ResolutionError(
                        component_type=ctype,
                        component_id=cid,
                        reason=f"{ctype} '{listing.name}' version '{cver}' is not approved (status: {status_str})",
                    )
                )
                continue
        elif require_approved and listing.status != ListingStatus.approved:
            errors.append(
                ResolutionError(
                    component_type=ctype,
                    component_id=cid,
                    reason=f"{ctype} '{listing.name}' is not approved (status: {listing.status.value})",
                )
            )

    return errors
