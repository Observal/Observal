# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Component source CRUD and sync endpoints."""

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import get_db, require_role
from models.component_source import ComponentSource
from models.user import User, UserRole
from schemas.component_source import (
    ComponentSourceCreate,
    ComponentSourceResponse,
    SyncResponse,
)
from services.audit_helpers import audit
from services.git_mirror_service import sync_source

router = APIRouter(prefix="/api/v1/component-sources", tags=["component-sources"])


@router.post("", response_model=ComponentSourceResponse, status_code=201)
async def add_source(
    req: ComponentSourceCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.user)),
):
    # Detect provider from URL
    provider = "github"
    url_lower = req.url.lower()
    if "gitlab" in url_lower:
        provider = "gitlab"
    elif "bitbucket" in url_lower:
        provider = "bitbucket"

    source = ComponentSource(
        url=req.url,
        provider=provider,
        component_type=req.component_type,
        is_public=req.is_public,
        owner_org_id=req.owner_org_id,
    )
    try:
        db.add(source)
        await db.commit()
        await db.refresh(source)
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="Source with this URL and component type already exists")

    await audit(
        current_user,
        "source.add",
        resource_type="component_source",
        resource_id=str(source.id),
        resource_name=source.url,
    )
    return ComponentSourceResponse.model_validate(source)


@router.get("", response_model=list[ComponentSourceResponse])
async def list_sources(
    component_type: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.user)),
):
    stmt = select(ComponentSource)
    if component_type:
        stmt = stmt.where(ComponentSource.component_type == component_type)
    result = await db.execute(stmt.order_by(ComponentSource.created_at.desc()))
    sources = result.scalars().all()
    await audit(current_user, "source.list", resource_type="component_source")
    return [ComponentSourceResponse.model_validate(s) for s in sources]


@router.get("/{source_id}", response_model=ComponentSourceResponse)
async def get_source(
    source_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.user)),
):
    source = await db.get(ComponentSource, source_id)
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")
    await audit(
        current_user,
        "source.view",
        resource_type="component_source",
        resource_id=str(source.id),
        resource_name=source.url,
    )
    return ComponentSourceResponse.model_validate(source)


@router.post("/{source_id}/sync", response_model=SyncResponse)
async def trigger_sync(
    source_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin)),
):
    source = await db.get(ComponentSource, source_id)
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")

    source.sync_status = "syncing"
    await db.commit()

    result = sync_source(source.url, source.component_type)

    source.last_synced_at = datetime.now(UTC)
    if result.success:
        source.sync_status = "success"
        source.sync_error = None
    else:
        source.sync_status = "failed"
        source.sync_error = result.error

    await db.commit()
    await db.refresh(source)

    await audit(
        current_user,
        "source.sync",
        resource_type="component_source",
        resource_id=str(source.id),
        resource_name=source.url,
        detail=f"Sync status={source.sync_status}",
    )
    return SyncResponse(
        source_id=source.id,
        status=source.sync_status,
        components_found=len(result.components),
        commit_sha=result.commit_sha,
        error=result.error or None,
    )


@router.delete("/{source_id}")
async def delete_source(
    source_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin)),
):
    source = await db.get(ComponentSource, source_id)
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")
    source_url = source.url
    await db.delete(source)
    await db.commit()
    await audit(
        current_user,
        "source.delete",
        resource_type="component_source",
        resource_id=str(source_id),
        resource_name=source_url,
    )
    return {"deleted": str(source_id)}
