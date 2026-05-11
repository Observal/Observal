# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

import uuid
from datetime import datetime, timedelta

from pydantic import BaseModel, Field


class ComponentSourceCreate(BaseModel):
    url: str = Field(..., min_length=10, pattern=r"^https://")
    component_type: str = Field(..., pattern="^(mcp|skill|hook|prompt|sandbox)$")
    is_public: bool = True
    owner_org_id: uuid.UUID | None = None


class ComponentSourceResponse(BaseModel):
    id: uuid.UUID
    url: str
    provider: str
    component_type: str
    is_public: bool
    owner_org_id: uuid.UUID | None
    auto_sync_interval: timedelta | None
    last_synced_at: datetime | None
    sync_status: str | None
    sync_error: str | None
    created_at: datetime
    model_config = {"from_attributes": True}


class SyncResponse(BaseModel):
    source_id: uuid.UUID
    status: str
    components_found: int
    commit_sha: str
    error: str | None = None
