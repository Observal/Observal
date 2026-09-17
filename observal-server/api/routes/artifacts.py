# SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""Permanent, versioned artifact URLs.

``GET /api/v1/artifacts/{kind}/{entity_id}/{version}`` serves the exact bytes
the discovery entry's ``url`` points at, with a ``Digest`` header the
capability lock records. The same version always returns the same bytes, so
approved artifacts are cached as immutable.

Visibility follows the discovery entry: whoever may see the entry may fetch
its artifacts. Versions other than the one the entry currently points at are
served too (a lock file may pin an older approved version), but never a
version the caller could not see through the registry.
"""

import uuid

from fastapi import APIRouter, Depends, Response
from fastapi.responses import JSONResponse
from loguru import logger as optic
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import services.dynamic_settings as ds
from api.deps import get_db, get_effective_agent_permission, get_effective_component_permission
from api.routes.ard import PUBLIC_SEARCH_SETTING, discovery_user
from models.discovery_entry import DiscoveryEntry, DiscoveryKind, DiscoveryLifecycle
from models.mcp import ListingStatus
from models.user import User
from services.discovery.adapters import ADAPTERS, NATIVE_MODELS
from services.discovery.visibility import visible_entries_predicate

router = APIRouter(prefix="/api/v1/artifacts", tags=["ard"])

_IMMUTABLE = "public, max-age=31536000, immutable"
_PRIVATE = "private, no-store"


def _error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"errorCode": code, "message": message})


@router.get("/{kind}/{entity_id}/{version}")
async def get_artifact(
    kind: str,
    entity_id: uuid.UUID,
    version: str,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(discovery_user),
) -> Response:
    try:
        discovery_kind = DiscoveryKind(kind)
    except ValueError:
        return _error(404, "NOT_FOUND", "Unknown artifact kind")
    if discovery_kind not in NATIVE_MODELS:
        return _error(404, "NOT_FOUND", "Artifacts are only served for native resources")
    if current_user is None and not await ds.get_bool(PUBLIC_SEARCH_SETTING, False):
        return _error(404, "NOT_FOUND", "Artifact not found")

    # The entry is the visibility gate: no entry the caller may see, no artifact.
    entry_stmt = select(DiscoveryEntry).where(
        DiscoveryEntry.kind == discovery_kind,
        DiscoveryEntry.local_entity_id == entity_id,
        visible_entries_predicate(current_user, lifecycles=tuple(DiscoveryLifecycle)),
    )
    entry = (await db.execute(entry_stmt)).scalar_one_or_none()
    if entry is None:
        return _error(404, "NOT_FOUND", "Artifact not found")

    listing_model, version_model, fk = NATIVE_MODELS[discovery_kind]
    listing = (await db.execute(select(listing_model).where(listing_model.id == entity_id))).scalar_one_or_none()
    if listing is None:
        return _error(404, "NOT_FOUND", "Artifact not found")
    version_stmt = select(version_model).where(
        getattr(version_model, fk) == entity_id, version_model.version == version
    )
    if discovery_kind == DiscoveryKind.agent:
        from sqlalchemy.orm import selectinload

        from models.agent import AgentVersion

        version_stmt = version_stmt.options(selectinload(AgentVersion.components))
    row = (await db.execute(version_stmt)).scalar_one_or_none()
    if row is None:
        return _error(404, "NOT_FOUND", "Version not found")

    # A non-approved version is only for people who could open it in the registry.
    status = getattr(row, "status", None)
    approved = getattr(status, "value", status) in (ListingStatus.approved.value, "approved")
    if not approved:
        permission = (
            get_effective_agent_permission(listing, current_user)
            if discovery_kind == DiscoveryKind.agent
            else get_effective_component_permission(listing, current_user)
        )
        if permission != "owner":
            return _error(404, "NOT_FOUND", "Version not found")

    projected = ADAPTERS[discovery_kind](listing, row)
    artifact = projected.artifact
    optic.debug("artifact served kind={} id={} version={} bytes={}", kind, entity_id, version, len(artifact.content))
    return Response(
        content=artifact.content,
        media_type=artifact.content_type,
        headers={
            "Digest": artifact.digest_header,
            "X-Artifact-Digest": artifact.digest,
            "X-Observal-Identifier": entry.ard_identifier,
            "Cache-Control": _IMMUTABLE if approved and entry.visibility.value == "public" else _PRIVATE,
        },
    )
