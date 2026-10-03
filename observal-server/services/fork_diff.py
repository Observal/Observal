# SPDX-FileCopyrightText: 2026 Naraen Rammoorthi <naraen13@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""Compare a visible fork release with its approved, currently visible upstream base."""

from __future__ import annotations

import difflib
from typing import TYPE_CHECKING

import yaml
from fastapi import HTTPException
from sqlalchemy import select

from api.deps import (
    get_effective_agent_permission,
    get_effective_component_permission,
    may_view_unapproved,
)
from models.agent import AgentStatus, AgentVersion
from models.mcp import ListingStatus
from services.agent_snapshot import build_yaml_snapshot
from services.registry_fork import COMPONENT_MODELS, provenance_for

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


def _render_diff(before: dict, after: dict, *, source: str, target: str) -> dict:
    left = yaml.safe_dump(before, sort_keys=True, allow_unicode=True).splitlines(keepends=True)
    right = yaml.safe_dump(after, sort_keys=True, allow_unicode=True).splitlines(keepends=True)
    diff = "".join(difflib.unified_diff(left, right, fromfile=source, tofile=target))
    return {"diff": diff, "unchanged": before == after}


async def fork_version_diff(db: AsyncSession, fork, kind: str, current_user, version: str | None = None) -> dict:
    """Never read the base snapshot unless the source is still accessible to this caller.

    A fork owner/reviewer may compare an unapproved fork version; other viewers
    only see approved releases. An inaccessible upstream always answers 404,
    without disclosing its saved reference, ID, or version.
    """
    if not getattr(fork, "is_fork", False):
        raise HTTPException(status_code=404, detail="Fork not found")
    provenance = await provenance_for(fork, current_user, db)
    if not provenance or not provenance["available"] or not provenance.get("version"):
        raise HTTPException(status_code=404, detail="Upstream unavailable")

    version_model = AgentVersion if kind == "agent" else COMPONENT_MODELS[kind][1]
    status = AgentStatus if kind == "agent" else ListingStatus
    fk = version_model.agent_id if kind == "agent" else version_model.listing_id
    permission = (
        get_effective_agent_permission(fork, current_user)
        if kind == "agent"
        else get_effective_component_permission(fork, current_user)
    )
    selected = (
        version if version is not None else (fork.latest_version.version if fork.latest_version is not None else None)
    )
    query = select(version_model).where(fk == fork.id, version_model.version == selected)
    if not may_view_unapproved(permission, current_user):
        query = query.where(version_model.status == status.approved)
    candidate = (await db.execute(query)).scalar_one_or_none()
    if candidate is None:
        raise HTTPException(status_code=404, detail="Version not found")

    source = await db.get(type(fork), fork.forked_from_id)
    base = await db.get(version_model, fork.forked_from_version_id)
    if (
        source is None
        or base is None
        or base.status != status.approved
        or (base.agent_id if kind == "agent" else base.listing_id) != source.id
    ):
        raise HTTPException(status_code=404, detail="Upstream unavailable")

    if kind == "agent":
        # Version numbers are release metadata, not content changes. Snapshots
        # are frozen at release; rebuild only for legacy rows without one.
        before = yaml.safe_load(base.yaml_snapshot or await build_yaml_snapshot(base, db)) or {}
        after = yaml.safe_load(candidate.yaml_snapshot or await build_yaml_snapshot(candidate, db)) or {}
        before.pop("version", None)
        after.pop("version", None)
    else:
        from api.routes.component_versions import _version_to_dict
        from services.agent_lock import _named, content_digest
        from services.registry_fork import VERSION_MANAGED_FIELDS

        # The install digest deliberately ignores secret environment/header
        # values. Show only their names/required flags, as the digest does.
        if content_digest(kind, base) == content_digest(kind, candidate):
            return {"version": candidate.version, "base_version": base.version, "diff": "", "unchanged": True}
        excluded = (VERSION_MANAGED_FIELDS - {"description"}) | {
            "mcp_validated",
            "validated",
            "validated_at",
            "tools_schema",
        }

        def visible_content(row):
            fields = {k: v for k, v in _version_to_dict(row, kind).items() if k not in excluded}
            for key in ("environment_variables", "headers"):
                if key in fields:
                    fields[key] = _named(fields[key])
            return fields

        before = visible_content(base)
        after = visible_content(candidate)
        if before == after:
            # Some install fields (notably skill scripts) are deliberately
            # absent from the public version serializer. Signal the content
            # change without exposing fields that endpoint does not publish.
            before["additional_install_content_digest"] = content_digest(kind, base)
            after["additional_install_content_digest"] = content_digest(kind, candidate)

    result = _render_diff(before, after, source=f"upstream@{base.version}", target=f"fork@{candidate.version}")
    return {"version": candidate.version, "base_version": base.version, **result}
