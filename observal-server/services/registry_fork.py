# SPDX-FileCopyrightText: 2026 Naraen Rammoorthi <naraen13@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""Independent registry forks: approved source selection and agent draft creation."""

from __future__ import annotations

import re
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from fastapi import HTTPException
from loguru import logger as optic
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from api.deps import check_listing_visibility_async
from models.agent import Agent, AgentStatus, AgentVersion
from models.hook import HookListing, HookVersion
from models.mcp import ListingStatus, McpListing, McpVersion
from models.prompt import PromptListing, PromptVersion
from models.sandbox import SandboxListing, SandboxVersion
from models.skill import SkillListing, SkillVersion
from models.team import Team
from services import dynamic_settings
from services.agent_lock import _pinned_row, _versions_for, attach_pinned_components, lock_agent_version
from services.agent_resolver import validate_component_ids
from services.agent_snapshot import build_yaml_snapshot
from services.harness_capability_inference import compute_supported_harnesses, infer_required_features
from services.redis import get_redis
from services.registry_namespace import identity_exists
from services.teamspace import resolve_publish_target

if TYPE_CHECKING:
    import uuid

    from sqlalchemy.ext.asyncio import AsyncSession

_FORK_SEMVER = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-[a-zA-Z0-9-]+(?:\.[a-zA-Z0-9-]+)*)?$")

COMPONENT_MODELS = {
    "mcp": (McpListing, McpVersion),
    "skill": (SkillListing, SkillVersion),
    "hook": (HookListing, HookVersion),
    "prompt": (PromptListing, PromptVersion),
    "sandbox": (SandboxListing, SandboxVersion),
}

VERSION_MANAGED_FIELDS = frozenset(
    {
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
        "base_version_id",
        "base_revision",
        "content_revision",
        "review_epoch",
        "requires_global_review",
        "pre_public_status",
        "pre_public_reviewed_by",
        "pre_public_reviewed_at",
    }
)


@dataclass(frozen=True)
class ForkRequestSpec:
    name: str | None = None
    version: str | None = None
    new_version: str | None = None
    team_id: uuid.UUID | None = None
    visibility: str | None = None


@dataclass
class ForkResult:
    entity: Any
    version: Any
    warnings: list[str]


def _copy_version_columns(version_model: type, base: Any, *, skip: frozenset[str] = VERSION_MANAGED_FIELDS) -> dict:
    """Deep-copy component content only; all release and review state is managed separately."""
    return {
        column.name: deepcopy(getattr(base, column.name))
        for column in version_model.__table__.columns
        if column.name not in skip
    }


def _valid_version(value: str) -> None:
    if len(value) > 50 or not _FORK_SEMVER.fullmatch(value):
        raise HTTPException(status_code=422, detail=f"Invalid semver string: {value!r}")


_ORDERABLE_VERSION = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z.-]+))?(?:\+[0-9A-Za-z.-]+)?$")


def _version_key(value: str) -> tuple:
    """SemVer precedence for stored versions; never raises on legacy strings.

    New input is validated strictly by ``_valid_version``. Existing approved
    rows may predate that rule, so an unparseable one sorts lowest instead of
    making the whole listing unforkable. A release outranks its prereleases,
    and numeric prerelease identifiers compare numerically, before text.
    """
    match = _ORDERABLE_VERSION.fullmatch(value or "")
    if match is None:
        return (0, 0, 0, 0, 0, ())
    major, minor, patch, prerelease = match.groups()
    identifiers = tuple(
        (0, int(part), "") if part.isdigit() else (1, 0, part) for part in (prerelease or "").split(".") if part
    )
    return (1, int(major), int(minor), int(patch), 0 if prerelease else 1, identifiers)


def _is_stable(version) -> bool:
    return not getattr(version, "is_prerelease", False) and "-" not in version.version


def _highest_approved(approved: list):
    """Highest stable approved release, else the highest approved prerelease."""
    stable = [v for v in approved if _is_stable(v)]
    return max(stable or approved, key=lambda v: _version_key(v.version))


def _select_base_version(versions: list, requested: str | None):
    if requested is not None:
        # An exact lookup: legacy approved version strings stay addressable.
        row = next((v for v in versions if v.version == requested and v.status == AgentStatus.approved), None)
        if row is None:
            raise HTTPException(status_code=404, detail="Version not found")
        return row
    approved = [v for v in versions if v.status == AgentStatus.approved]
    if not approved:
        raise HTTPException(status_code=409, detail="Agent has no approved version to fork")
    return _highest_approved(approved)


def _fork_version_string(base, new_version: str | None) -> str:
    if new_version is not None:
        _valid_version(new_version)
        return new_version
    if not _FORK_SEMVER.fullmatch(base.version) or len(base.version) > 50:
        raise HTTPException(
            status_code=422,
            detail=f"Base version {base.version!r} is not valid SemVer; choose a new_version for the fork",
        )
    return base.version


async def _check_rate_limit(user_id: uuid.UUID) -> None:
    if not await dynamic_settings.get_bool("registry.fork.enabled"):
        raise HTTPException(status_code=403, detail="Forking is disabled by your administrator")
    limit = await dynamic_settings.get_int("registry.fork.max_per_user_per_hour")
    if limit <= 0:
        raise HTTPException(status_code=429, detail="Fork limit reached; retry in one hour")
    # One atomic operation: the first hit starts the one-hour window, even under concurrency.
    try:
        count = await get_redis().eval(
            "local n = redis.call('INCR', KEYS[1]); if n == 1 then redis.call('EXPIRE', KEYS[1], 3600) end; return n",
            1,
            f"fork:rate:{user_id}",
        )
    except Exception as exc:
        # The limit is a safety control: fail closed, but as a clear retryable 503.
        optic.warning("fork rate limiter unavailable: {}", type(exc).__name__)
        raise HTTPException(status_code=503, detail="Forking is temporarily unavailable; retry shortly") from exc
    if count > limit:
        raise HTTPException(status_code=429, detail="Fork limit reached; retry in one hour")


async def _release_fork_slot(user_id: uuid.UUID) -> None:
    """Return a reserved slot when the fork was not created; never fail the request."""
    try:
        await get_redis().eval(
            "if redis.call('GET', KEYS[1]) and tonumber(redis.call('GET', KEYS[1])) > 0 then "
            "return redis.call('DECR', KEYS[1]) end; return 0",
            1,
            f"fork:rate:{user_id}",
        )
    except Exception as exc:
        optic.warning("fork rate slot release failed: {}", type(exc).__name__)


async def _flush_new_identity(db: AsyncSession, label: str, target) -> None:
    """Map a concurrent namespace/slug insert to 409 at the flush that detects it.

    The pre-check cannot close the race; the unique index fails here, before
    the route's ``commit_or_name_conflict`` could translate it.
    """
    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        detail = str(exc.orig).lower()
        if ("namespace" in detail or "slug" in detail) and ("unique" in detail or "duplicate" in detail):
            raise HTTPException(
                status_code=409, detail=f"{label} '{target.namespace}/{target.slug}' already exists"
            ) from exc
        raise


async def _enforce_private_source_policy(source: Agent, target, user, db: AsyncSession) -> None:
    if not source.is_private:
        return
    if source.team_id is None:
        # Legacy private personal listings may only move to this creator's private
        # personal teamspace. A public personal target would leak their content.
        if (
            getattr(source, "created_by", getattr(source, "submitted_by", None)) == user.id
            and target.team_id
            and target.visibility == "team"
        ):
            team = await db.get(Team, target.team_id)
            if team and team.is_personal and team.is_private and team.created_by == user.id:
                return
    elif target.team_id == source.team_id and target.visibility == "team":
        return
    raise HTTPException(status_code=409, detail="Private items can only be forked into their own private teamspace")


async def fork_agent(db: AsyncSession, source: Agent, spec: ForkRequestSpec, *, current_user) -> ForkResult:
    if source.deleted_at is not None or source.status != AgentStatus.approved:
        raise HTTPException(status_code=409, detail="Source is not approved")
    base = _select_base_version(source.versions, spec.version)
    version_string = _fork_version_string(base, spec.new_version)
    name = spec.name or source.name
    try:
        target = await resolve_publish_target(db, current_user, name, team_id=spec.team_id, visibility=spec.visibility)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    await _enforce_private_source_policy(source, target, current_user, db)
    if await identity_exists(db, Agent, target.namespace, target.slug):
        raise HTTPException(status_code=409, detail=f"Agent '{target.namespace}/{target.slug}' already exists")

    # Before writing, resolve the source's exact pins. A previous pin bypasses
    # require_approved inside attach_pinned_components; never pass it unchecked.
    pins = list(base.components)
    versions = await _versions_for(db, [(p.component_type, p.component_id) for p in pins])
    refs = []
    warnings = []
    for pin in pins:
        rows = versions.get((pin.component_type, pin.component_id), [])
        row, _ = _pinned_row(pin, rows)
        if row is None or row.status.value != "approved":
            approved = [v for v in rows if v.status.value == "approved"]
            if not approved:
                raise HTTPException(
                    status_code=409, detail=f"{pin.component_type} {pin.component_id} has no approved version"
                )
            row = _highest_approved(approved)
            warnings.append(f"Re-pinned {pin.component_type} {pin.component_id} to approved {row.version}")
        refs.append(
            {
                "component_type": pin.component_type,
                "component_id": pin.component_id,
                "component_name": pin.component_name,
                "config_override": deepcopy(pin.config_override),
                "version": row.version,
            }
        )
    errors = await validate_component_ids(
        refs,
        db,
        require_approved=False,  # A newer pending listing may retain an approved pinned version.
        current_user=current_user,
        target_team_id=target.team_id if target.visibility == "team" else None,
        enforce_target=True,
    )
    if errors:
        raise HTTPException(
            status_code=409,
            detail="Components unavailable for fork target: "
            + ", ".join(f"{e.component_type} {e.component_id}" for e in errors),
        )
    # Reserve quota only after every validation passed, so a rejected request
    # (conflict, bad version, wrong target) never consumes the user's limit.
    await _check_rate_limit(current_user.id)
    try:
        agent = Agent(
            name=name,
            namespace=target.namespace,
            slug=target.slug,
            owner=target.owner,
            team_id=target.team_id,
            is_private=target.visibility == "team",
            created_by=current_user.id,
            category=source.category,
            co_authors=[],
            is_recommended=False,
            forked_from_id=source.id,
            forked_from_version_id=base.id,
            forked_from_ref=f"{source.qualified_name}@{base.version}",
            forked_at=datetime.now(UTC),
        )
        db.add(agent)
        await _flush_new_identity(db, "Agent", target)
        version = AgentVersion(
            agent_id=agent.id,
            version=version_string,
            description=base.description,
            prompt=base.prompt,
            model_name=base.model_name,
            model_config_json=deepcopy(base.model_config_json or {}),
            models_by_harness=deepcopy(base.models_by_harness or {}),
            external_mcps=deepcopy(base.external_mcps or []),
            supported_harnesses=deepcopy(base.supported_harnesses or []),
            success_criteria=deepcopy(base.success_criteria),
            status=AgentStatus.draft,
            is_prerelease="-" in version_string,
            released_by=current_user.id,
        )
        db.add(version)
        await db.flush()
        agent.latest_version_id = version.id
        await attach_pinned_components(db, version.id, refs, require_approved=True, current_user=current_user)
        skill_ids = [ref["component_id"] for ref in refs if ref["component_type"] == "skill"]
        skills = {}
        if skill_ids:
            rows = (await db.execute(select(SkillListing).where(SkillListing.id.in_(skill_ids)))).scalars().all()
            skills = {row.id: row for row in rows}

        class _Proxy:
            components = [
                type("_Ref", (), {"component_type": ref["component_type"], "component_id": ref["component_id"]})()
                for ref in refs
            ]
            external_mcps = version.external_mcps

        version.required_capabilities = infer_required_features(_Proxy(), skill_listings=skills)
        version.inferred_supported_harnesses = compute_supported_harnesses(version.required_capabilities)
        await db.flush()
        await lock_agent_version(db, agent, version)
        version.yaml_snapshot = await build_yaml_snapshot(version, db)
        return ForkResult(agent, version, warnings)
    except BaseException:
        await _release_fork_slot(current_user.id)
        raise


async def fork_component(
    db: AsyncSession, component_type: str, source, spec: ForkRequestSpec, *, current_user
) -> ForkResult:
    """Copy only an approved component release into an independent draft listing."""
    listing_model, version_model = COMPONENT_MODELS[component_type]
    if source.status != ListingStatus.approved:
        raise HTTPException(status_code=409, detail="Source is not approved")
    base = _select_base_version(source.versions, spec.version)
    version_string = _fork_version_string(base, spec.new_version)
    name = spec.name or source.name
    try:
        target = await resolve_publish_target(db, current_user, name, team_id=spec.team_id, visibility=spec.visibility)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    await _enforce_private_source_policy(source, target, current_user, db)
    if await identity_exists(db, listing_model, target.namespace, target.slug):
        raise HTTPException(
            status_code=409, detail=f"{component_type} '{target.namespace}/{target.slug}' already exists"
        )

    await _check_rate_limit(current_user.id)
    try:
        listing = listing_model(
            **({"category": source.category} if component_type == "mcp" else {}),
            name=name,
            namespace=target.namespace,
            slug=target.slug,
            owner=target.owner,
            team_id=target.team_id,
            is_private=target.visibility == "team",
            submitted_by=current_user.id,
            co_authors=[],
            bundle_id=None,
            unique_agents=0,
            is_recommended=False,
            forked_from_id=source.id,
            forked_from_version_id=base.id,
            forked_from_ref=f"{source.qualified_name}@{base.version}",
            forked_at=datetime.now(UTC),
        )
        db.add(listing)
        await _flush_new_identity(db, component_type, target)
        content = _copy_version_columns(version_model, base)
        content.update(
            listing_id=listing.id,
            version=version_string,
            description=base.description,
            changelog=None,
            status=ListingStatus.draft,
            released_by=current_user.id,
            released_at=datetime.now(UTC),
        )
        if component_type == "mcp":
            content["mcp_validated"] = False
        elif component_type == "skill":
            content["validated"] = False
        elif component_type == "sandbox":
            content["validated_at"] = None
        version = version_model(**content)
        db.add(version)
        await db.flush()
        listing.latest_version_id = version.id
        return ForkResult(listing, version, [])
    except BaseException:
        await _release_fork_slot(current_user.id)
        raise


async def provenance_for(entity: Agent, current_user, db: AsyncSession) -> dict | None:
    if getattr(entity, "is_fork", False) is not True:
        return None
    unavailable = {"available": False, "forked_at": entity.forked_at}
    if entity.forked_from_id is None:
        return unavailable
    listing_model = type(entity)
    version_model = (
        AgentVersion
        if listing_model is Agent
        else next(version for listing, version in COMPONENT_MODELS.values() if listing is listing_model)
    )
    source = await db.get(listing_model, entity.forked_from_id)
    if source is None or getattr(source, "deleted_at", None) is not None:
        return unavailable
    if not await check_listing_visibility_async(source, current_user, db):
        return unavailable
    if source.status.value != "approved" and getattr(
        source, "created_by", getattr(source, "submitted_by", None)
    ) != getattr(current_user, "id", None):
        return unavailable
    base = await db.get(version_model, entity.forked_from_version_id) if entity.forked_from_version_id else None
    return {
        "available": True,
        "id": source.id,
        "type": "agent"
        if listing_model is Agent
        else next(key for key, models in COMPONENT_MODELS.items() if models[0] is listing_model),
        "namespace": source.namespace,
        "slug": source.slug,
        "qualified_name": source.qualified_name,
        "version": base.version
        if base is not None
        and (base.agent_id if listing_model is Agent else base.listing_id) == source.id
        and base.status.value == "approved"
        else None,
        "forked_at": entity.forked_at,
    }


def public_agent_fork_condition():
    """The shared predicate for count and Forks list (latest release must be public)."""
    return (
        (Agent.is_private.is_(False))
        & (Agent.deleted_at.is_(None))
        & (Agent.latest_version_id == AgentVersion.id)
        & (AgentVersion.status == AgentStatus.approved)
    )


def public_component_fork_condition(listing_model, version_model):
    return (
        listing_model.is_private.is_(False)
        & (listing_model.latest_version_id == version_model.id)
        & (version_model.status == ListingStatus.approved)
    )


async def component_fork_counts(
    db: AsyncSession, listing_model, version_model, ids: list[uuid.UUID]
) -> dict[uuid.UUID, int]:
    if not ids:
        return {}
    rows = await db.execute(
        select(listing_model.forked_from_id, func.count(listing_model.id))
        .join(version_model, listing_model.latest_version_id == version_model.id)
        .where(public_component_fork_condition(listing_model, version_model), listing_model.forked_from_id.in_(ids))
        .group_by(listing_model.forked_from_id)
    )
    return {source_id: count for source_id, count in rows.all()}


async def agent_fork_counts(db: AsyncSession, ids: list[uuid.UUID]) -> dict[uuid.UUID, int]:
    if not ids:
        return {}
    rows = await db.execute(
        select(Agent.forked_from_id, func.count(Agent.id))
        .join(AgentVersion, Agent.latest_version_id == AgentVersion.id)
        .where(public_agent_fork_condition(), Agent.forked_from_id.in_(ids))
        .group_by(Agent.forked_from_id)
    )
    return {source_id: count for source_id, count in rows.all()}
