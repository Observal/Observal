# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

import json
import logging

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import get_db, require_role
from models.agent import Agent, AgentStatus, AgentVersion, AgentVisibility
from models.agent_component import AgentComponent
from models.user import User, UserRole
from schemas.bulk import BulkAgentItem, BulkAgentRequest, BulkResult, BulkResultItem
from services.audit_helpers import audit
from services.registry_telemetry import emit_registry_event

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/bulk", tags=["bulk"])


async def _agent_name_exists(name: str, user_id, db: AsyncSession) -> bool:
    """Check whether the authenticated user already owns an agent with the given name."""
    result = await db.execute(select(Agent.id).where(Agent.name == name, Agent.created_by == user_id))
    return result.scalar_one_or_none() is not None


async def _create_single_agent(
    item: BulkAgentItem,
    user: User,
    db: AsyncSession,
) -> Agent:
    """Create a single Agent + AgentVersion row (with components and goal template)."""
    agent = Agent(
        name=item.name,
        owner=item.owner or user.email,
        created_by=user.id,
        owner_org_id=user.org_id,
        visibility=AgentVisibility.public,
    )
    db.add(agent)
    await db.flush()

    version = AgentVersion(
        agent_id=agent.id,
        version=item.version,
        description=item.description,
        prompt=item.prompt,
        model_name=item.model_name,
        model_config_json=item.model_config_json,
        external_mcps=item.external_mcps,
        supported_ides=item.supported_ides,
        status=AgentStatus.pending,
        released_by=user.id,
    )
    db.add(version)
    await db.flush()

    agent.latest_version_id = version.id

    # Attach components
    for i, comp in enumerate(item.components):
        db.add(
            AgentComponent(
                agent_version_id=version.id,
                component_type=comp.get("component_type", "mcp"),
                component_id=comp["component_id"],
                component_name=comp.get("component_name", ""),
                resolved_version="latest",
                order_index=i,
                config_override=comp.get("config_override"),
            )
        )

    return agent


@router.post("/agents", response_model=BulkResult)
async def bulk_create_agents(
    request: BulkAgentRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.user)),
):
    """Create multiple agents in a single request.

    Duplicate names (agents already owned by the caller) are skipped.
    When ``dry_run=True`` no agents are persisted — the response previews
    what *would* happen.
    """
    results: list[BulkResultItem] = []
    created = 0
    skipped = 0
    errors = 0

    for item in request.agents:
        # Check for duplicate name
        if await _agent_name_exists(item.name, current_user.id, db):
            results.append(
                BulkResultItem(name=item.name, status="skipped", error="Agent with this name already exists")
            )
            skipped += 1
            continue

        if request.dry_run:
            results.append(BulkResultItem(name=item.name, status="created"))
            created += 1
            continue

        try:
            agent = await _create_single_agent(item, current_user, db)
            results.append(BulkResultItem(name=item.name, status="created", agent_id=agent.id))
            created += 1
        except Exception as exc:
            logger.warning("bulk create failed for agent '%s': %s", item.name, exc)
            results.append(BulkResultItem(name=item.name, status="error", error=str(exc)))
            errors += 1

    if not request.dry_run and created > 0:
        await db.commit()

        emit_registry_event(
            action="agent.bulk_create",
            user_id=str(current_user.id),
            user_email=current_user.email,
            user_role=current_user.role.value,
            metadata={"total": str(len(request.agents)), "created": str(created), "skipped": str(skipped)},
        )

        await audit(
            current_user,
            "agent.bulk_create",
            resource_type="agent",
            detail=json.dumps({"count": created, "skipped": skipped, "errors": errors}),
        )

    return BulkResult(
        total=len(request.agents),
        created=created,
        skipped=skipped,
        errors=errors,
        dry_run=request.dry_run,
        results=results,
    )
