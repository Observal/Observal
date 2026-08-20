# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: Apache-2.0


from fastapi import APIRouter, Depends
from loguru import logger as optic
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import get_db, registry_identity, require_role
from models.agent import Agent, AgentStatus, AgentVersion
from models.agent_component import AgentComponent
from models.user import User, UserRole
from schemas.bulk import BulkAgentItem, BulkAgentRequest, BulkResult, BulkResultItem
from services.inbox import sources as inbox
from services.registry_telemetry import emit_registry_event

router = APIRouter(prefix="/api/v1/bulk", tags=["bulk"])


async def _agent_name_exists(name: str, user: User, db: AsyncSession) -> bool:
    """Check whether the authenticated user's namespace already contains the slug."""
    namespace, slug = registry_identity(user, name)
    optic.trace("namespace={}, slug={}", namespace, slug)
    result = await db.execute(
        select(Agent.id).where(
            Agent.namespace == namespace,
            Agent.slug == slug,
            Agent.deleted_at.is_(None),
        )
    )
    return result.scalar_one_or_none() is not None


async def _create_single_agent(
    item: BulkAgentItem,
    user: User,
    db: AsyncSession,
) -> Agent:
    """Create a single Agent + AgentVersion row (with components and goal template)."""
    optic.trace("name={}, user_id={}", item.name, user.id)
    namespace, slug = registry_identity(user, item.name)
    agent = Agent(
        name=item.name,
        namespace=namespace,
        slug=slug,
        owner=item.owner or user.email,
        created_by=user.id,
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
        supported_harnesses=item.supported_harnesses,
        status=AgentStatus.pending,
        released_by=user.id,
    )
    db.add(version)
    await db.flush()

    agent.latest_version_id = version.id

    from services.agent_resolver import resolve_component_versions

    component_versions = await resolve_component_versions(item.components, db)

    # Attach components
    for i, comp in enumerate(item.components):
        db.add(
            AgentComponent(
                agent_version_id=version.id,
                component_type=comp.get("component_type", "mcp"),
                component_id=comp["component_id"],
                component_name=comp.get("component_name", ""),
                resolved_version=component_versions.get(
                    (comp.get("component_type", "mcp"), comp["component_id"]), "latest"
                ),
                order_index=i,
                config_override=comp.get("config_override"),
            )
        )

    # Every bulk-created version lands in the review queue as pending, so the
    # reviewers who own that queue are told — same as a one-at-a-time submit.
    await inbox.on_publish(
        db,
        agent,
        subject_type="agent",
        actor_id=user.id,
        auto_approved=False,
        version=item.version,
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
    When ``dry_run=True`` no agents are persisted - the response previews
    what *would* happen.
    """
    optic.debug("bulk create agents")
    results: list[BulkResultItem] = []
    created = 0
    skipped = 0
    errors = 0
    seen_identities: set[tuple[str, str]] = set()

    for item in request.agents:
        try:
            identity = registry_identity(current_user, item.name)
        except ValueError:
            results.append(BulkResultItem(name=item.name, status="error", error="Agent name is invalid"))
            errors += 1
            continue

        if identity in seen_identities:
            results.append(
                BulkResultItem(name=item.name, status="skipped", error="Agent name is duplicated in this batch")
            )
            skipped += 1
            continue
        seen_identities.add(identity)

        # Check for duplicate name
        if await _agent_name_exists(item.name, current_user, db):
            results.append(
                BulkResultItem(name=item.name, status="skipped", error="Agent with this name already exists")
            )
            skipped += 1
            continue

        if request.dry_run:
            try:
                from services.agent_resolver import validate_component_ids

                component_errors = await validate_component_ids(
                    item.components,
                    db,
                    require_approved=False,
                    current_user=current_user,
                )
                if component_errors:
                    raise ValueError("component validation failed")
            except Exception as exc:
                optic.warning(
                    "bulk dry-run validation failed for agent '{}': error_type={}", item.name, type(exc).__name__
                )
                results.append(BulkResultItem(name=item.name, status="error", error="Agent definition is invalid"))
                errors += 1
                continue
            results.append(BulkResultItem(name=item.name, status="created"))
            created += 1
            continue

        try:
            # One SAVEPOINT per item, so "this item failed" and "this item was
            # not written" mean the same thing.
            #
            # Every item shares one transaction, and _create_single_agent
            # flushes as it goes: the Agent, then its version, then its
            # component rows, then the review notifications for whoever owns
            # that queue. Without a savepoint a failure partway through leaves
            # the rows it already flushed sitting in the transaction, and the
            # commit below persists a half-built agent that this loop just
            # reported to the caller as an error.
            #
            # On Postgres it is worse than partial data. A database-level error
            # aborts the whole transaction, so every later item fails on its
            # first statement and the final commit fails too — one bad row
            # turns into a wholly failed batch. Rolling back to the savepoint
            # clears that state and lets the remaining items proceed.
            async with db.begin_nested():
                agent = await _create_single_agent(item, current_user, db)
            results.append(BulkResultItem(name=item.name, status="created", agent_id=agent.id))
            created += 1
        except Exception as exc:
            optic.warning("bulk create failed for agent '{}': error_type={}", item.name, type(exc).__name__)
            results.append(BulkResultItem(name=item.name, status="error", error="Agent could not be created"))
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

    return BulkResult(
        total=len(request.agents),
        created=created,
        skipped=skipped,
        errors=errors,
        partial=errors > 0,
        dry_run=request.dry_run,
        results=results,
    )
