# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Shared helpers for agent route sub-modules."""

import uuid

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from api.deps import resolve_prefix_id
from models.agent import Agent, AgentStatus, AgentVersion
from models.mcp import ListingStatus, McpListing, McpVersion
from schemas.agent import (
    AgentResponse,
    ComponentLinkResponse,
    McpLinkResponse,
)

# Eager-load options for Agent queries to avoid MissingGreenlet in async.
_agent_load_options = [
    selectinload(Agent.team_accesses),
]


async def _load_agent(
    db: AsyncSession,
    agent_id: str,
    extra_conditions=None,
    *,
    prefer_user_id: uuid.UUID | None = None,
    org_id: uuid.UUID | None = None,
    include_all_statuses: bool = False,
) -> Agent | None:
    """Load an agent by UUID, prefix, or name with eager loading.

    When *prefer_user_id* is provided and resolution is by name, prefer the
    caller's own agent over agents created by other users with the same name.
    The global name fallback is restricted to active agents and, when *org_id*
    is set, to agents within the same organisation.

    Set *include_all_statuses* to find agents regardless of version status
    (needed for unarchive, delete, etc.).
    """
    try:
        return await resolve_prefix_id(
            Agent, agent_id, db, load_options=_agent_load_options, extra_conditions=extra_conditions
        )
    except HTTPException:
        pass

    # Try the caller's own agent first
    if prefer_user_id is not None:
        stmt = (
            select(Agent)
            .where(Agent.name == agent_id, Agent.created_by == prefer_user_id)
            .options(*_agent_load_options)
        )
        if extra_conditions:
            stmt = stmt.where(*extra_conditions)
        mine = (await db.execute(stmt)).scalar_one_or_none()
        if mine:
            return mine

    # Fall back to global name lookup
    stmt = (
        select(Agent)
        .join(AgentVersion, Agent.latest_version_id == AgentVersion.id)
        .where(Agent.name == agent_id)
        .options(*_agent_load_options)
    )
    if not include_all_statuses:
        stmt = stmt.where(AgentVersion.status == AgentStatus.approved)
    if extra_conditions:
        stmt = stmt.where(*extra_conditions)
    if org_id is not None:
        stmt = stmt.where(Agent.owner_org_id == org_id)
    results = (await db.execute(stmt)).scalars().all()
    if len(results) == 1:
        return results[0]

    return None


def _agent_to_response(
    agent: Agent,
    name_map: dict[str, str] | None = None,
    *,
    created_by_email: str = "",
    created_by_username: str | None = None,
    user_permission: str | None = None,
) -> AgentResponse:
    name_map = name_map or {}
    # Build mcp_links from components with component_type='mcp' (backwards compat)
    mcp_components = [c for c in agent.components if c.component_type == "mcp"]
    mcp_links = [
        McpLinkResponse(
            mcp_listing_id=comp.component_id,
            mcp_name=name_map.get(str(comp.component_id), "(component)"),
            order=comp.order_index,
        )
        for comp in mcp_components
    ]
    # Build full component_links for all types
    component_links = [
        ComponentLinkResponse(
            component_type=comp.component_type,
            component_id=comp.component_id,
            component_name=name_map.get(str(comp.component_id), ""),
            version_ref=comp.resolved_version,
            order=comp.order_index,
            config_override=comp.config_override,
        )
        for comp in agent.components
    ]
    # Build agent_dict from table columns plus version-delegate properties.
    agent_dict = {c.key: getattr(agent, c.key) for c in Agent.__table__.columns}
    for field in (
        "version",
        "description",
        "prompt",
        "model_name",
        "model_config_json",
        "models_by_ide",
        "external_mcps",
        "supported_ides",
        "required_ide_features",
        "inferred_supported_ides",
        "status",
        "rejection_reason",
    ):
        agent_dict[field] = getattr(agent, field)
    if not isinstance(agent_dict.get("models_by_ide"), dict):
        agent_dict["models_by_ide"] = {}
    agent_dict["mcp_links"] = mcp_links
    agent_dict["component_links"] = component_links
    agent_dict["visibility"] = agent.visibility
    agent_dict["team_accesses"] = [
        {"group_name": acc.group_name, "permission": acc.permission} for acc in getattr(agent, "team_accesses", [])
    ]
    agent_dict["created_by_email"] = created_by_email
    agent_dict["created_by_username"] = created_by_username
    agent_dict["user_permission"] = user_permission
    # Populate version fields for CLI pull resolution
    approved_versions = [
        v for v in getattr(agent, "versions", []) if getattr(v, "status", None) == AgentStatus.approved
    ]
    latest_approved = max(approved_versions, key=lambda v: v.created_at) if approved_versions else None
    agent_dict["latest_approved_version"] = latest_approved.version if latest_approved else None
    agent_dict["latest_version"] = agent.version if agent.version != "0.0.0" else None
    return AgentResponse(**agent_dict)


async def _resolve_component_names(components: list, db: AsyncSession) -> dict[str, str]:
    """Batch-resolve component_id -> name for all component types."""
    if not components:
        return {}
    from services.agent_resolver import _LISTING_MODELS

    # Group component_ids by type
    by_type: dict[str, list[uuid.UUID]] = {}
    for comp in components:
        by_type.setdefault(comp.component_type, []).append(comp.component_id)

    name_map: dict[str, str] = {}
    for comp_type, ids in by_type.items():
        model = _LISTING_MODELS.get(comp_type)
        if not model:
            continue
        rows = (await db.execute(select(model.id, model.name).where(model.id.in_(ids)))).all()
        for row in rows:
            name_map[str(row[0])] = row[1]
    return name_map


async def _validate_mcp_ids(mcp_ids: list[uuid.UUID], db: AsyncSession) -> list[McpListing]:
    listings = []
    for mid in mcp_ids:
        result = await db.execute(
            select(McpListing)
            .join(McpVersion, McpListing.latest_version_id == McpVersion.id)
            .where(McpListing.id == mid, McpVersion.status == ListingStatus.approved)
        )
        listing = result.scalar_one_or_none()
        if not listing:
            raise HTTPException(status_code=400, detail=f"MCP server {mid} not found or not approved")
        listings.append(listing)
    return listings
