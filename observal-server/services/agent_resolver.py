"""Agent composition resolver — looks up and validates all components for an agent."""

import logging
import uuid
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.agent import Agent
from models.agent_component import AgentComponent
from models.hook import HookListing
from models.mcp import ListingStatus, McpListing
from models.prompt import PromptListing
from models.sandbox import SandboxListing
from models.skill import SkillListing

logger = logging.getLogger(__name__)

# Maps component_type string to its ORM model
_LISTING_MODELS: dict[str, type] = {
    "mcp": McpListing,
    "skill": SkillListing,
    "hook": HookListing,
    "prompt": PromptListing,
    "sandbox": SandboxListing,
}


@dataclass
class ResolvedComponent:
    """A fully resolved component with its listing data."""
    component_type: str
    component_id: uuid.UUID
    name: str
    version: str
    git_url: str
    git_ref: str
    description: str
    order_index: int
    config_override: dict | None = None
    listing_status: str = ""
    # Type-specific fields carried through for config generation
    extra: dict = field(default_factory=dict)


@dataclass
class ResolutionError:
    """A single resolution failure."""
    component_type: str
    component_id: uuid.UUID
    reason: str


@dataclass
class ResolvedAgent:
    """Complete resolution result for an agent."""
    agent_id: uuid.UUID
    agent_name: str
    agent_version: str
    components: list[ResolvedComponent] = field(default_factory=list)
    errors: list[ResolutionError] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return len(self.errors) == 0

    def components_by_type(self, component_type: str) -> list[ResolvedComponent]:
        return [c for c in self.components if c.component_type == component_type]


def _extract_extra(listing, component_type: str) -> dict:
    """Pull type-specific fields from a listing into a flat dict for downstream use."""
    if component_type == "mcp":
        return {
            "transport": getattr(listing, "transport", None),
            "tools_schema": getattr(listing, "tools_schema", None),
            "fastmcp_validated": getattr(listing, "fastmcp_validated", False),
            "setup_instructions": getattr(listing, "setup_instructions", None),
        }
    if component_type == "skill":
        return {
            "skill_path": getattr(listing, "skill_path", "/"),
            "task_type": getattr(listing, "task_type", ""),
            "slash_command": getattr(listing, "slash_command", None),
            "triggers": getattr(listing, "triggers", None),
            "has_scripts": getattr(listing, "has_scripts", False),
            "is_power": getattr(listing, "is_power", False),
            "mcp_server_config": getattr(listing, "mcp_server_config", None),
        }
    if component_type == "hook":
        return {
            "event": getattr(listing, "event", ""),
            "execution_mode": getattr(listing, "execution_mode", "async"),
            "priority": getattr(listing, "priority", 100),
            "handler_type": getattr(listing, "handler_type", ""),
            "handler_config": getattr(listing, "handler_config", {}),
            "scope": getattr(listing, "scope", "agent"),
        }
    if component_type == "prompt":
        return {
            "template": getattr(listing, "template", ""),
            "variables": getattr(listing, "variables", []),
            "category": getattr(listing, "category", ""),
        }
    if component_type == "sandbox":
        return {
            "runtime_type": getattr(listing, "runtime_type", ""),
            "image": getattr(listing, "image", ""),
            "resource_limits": getattr(listing, "resource_limits", {}),
            "network_policy": getattr(listing, "network_policy", "none"),
            "entrypoint": getattr(listing, "entrypoint", None),
        }
    return {}


async def resolve_agent(
    agent: Agent,
    db: AsyncSession,
    *,
    require_approved: bool = True,
) -> ResolvedAgent:
    """Resolve all components for an agent.

    Looks up each AgentComponent's listing in the correct table,
    validates status, and returns a ResolvedAgent with full details.
    """
    result = ResolvedAgent(
        agent_id=agent.id,
        agent_name=agent.name,
        agent_version=agent.version,
    )

    for comp in agent.components:
        model = _LISTING_MODELS.get(comp.component_type)
        if model is None:
            result.errors.append(ResolutionError(
                component_type=comp.component_type,
                component_id=comp.component_id,
                reason=f"Unknown component type: {comp.component_type}",
            ))
            continue

        stmt = select(model).where(model.id == comp.component_id)
        listing = (await db.execute(stmt)).scalar_one_or_none()

        if listing is None:
            result.errors.append(ResolutionError(
                component_type=comp.component_type,
                component_id=comp.component_id,
                reason=f"{comp.component_type} listing {comp.component_id} not found",
            ))
            continue

        if require_approved and listing.status != ListingStatus.approved:
            result.errors.append(ResolutionError(
                component_type=comp.component_type,
                component_id=comp.component_id,
                reason=f"{comp.component_type} '{listing.name}' is not approved (status: {listing.status.value})",
            ))
            continue

        result.components.append(ResolvedComponent(
            component_type=comp.component_type,
            component_id=comp.component_id,
            name=listing.name,
            version=listing.version,
            git_url=listing.git_url,
            git_ref=listing.git_ref or "",
            description=listing.description,
            order_index=comp.order_index,
            config_override=comp.config_override,
            listing_status=listing.status.value,
            extra=_extract_extra(listing, comp.component_type),
        ))

    return result


async def validate_component_ids(
    components: list[dict],
    db: AsyncSession,
    *,
    require_approved: bool = True,
) -> list[ResolutionError]:
    """Validate a list of component references before attaching them to an agent.

    Each dict should have 'component_type' and 'component_id' keys.
    Returns a list of errors (empty if all valid).
    """
    errors = []
    for ref in components:
        ctype = ref.get("component_type", "")
        cid = ref.get("component_id")
        model = _LISTING_MODELS.get(ctype)
        if model is None:
            errors.append(ResolutionError(
                component_type=ctype,
                component_id=cid or uuid.UUID(int=0),
                reason=f"Unknown component type: {ctype}",
            ))
            continue

        stmt = select(model).where(model.id == cid)
        listing = (await db.execute(stmt)).scalar_one_or_none()

        if listing is None:
            errors.append(ResolutionError(
                component_type=ctype,
                component_id=cid,
                reason=f"{ctype} listing {cid} not found",
            ))
            continue

        if require_approved and listing.status != ListingStatus.approved:
            errors.append(ResolutionError(
                component_type=ctype,
                component_id=cid,
                reason=f"{ctype} '{listing.name}' is not approved (status: {listing.status.value})",
            ))

    return errors
