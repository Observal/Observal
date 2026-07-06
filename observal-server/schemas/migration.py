# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""Pydantic schemas for data migration API."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from models.migration_job import MigrationOperation, MigrationScope, MigrationStatus


class StartExportRequest(BaseModel):
    scope: MigrationScope


class StartImportRequest(BaseModel):
    scope: MigrationScope
    org_id: str | None = None
    project_id: str | None = None


class StartValidateRequest(BaseModel):
    scope: MigrationScope


class ArtifactMeta(BaseModel):
    name: str
    size_bytes: int
    sha256: str
    kind: Literal["archive", "parquet", "manifest"]


class MigrationJobResponse(BaseModel):
    id: str
    operation_type: MigrationOperation
    data_scope: MigrationScope
    status: MigrationStatus
    progress_phase: str | None = None
    progress_pct: int = 0
    progress_message: str | None = None
    error_message: str | None = None
    created_at: datetime
    finished_at: datetime | None = None
    artifacts: list[ArtifactMeta] = []
    result: dict | None = None
    schema_version: str | None = None
    model_config = {"from_attributes": True}


class DownloadTokenResponse(BaseModel):
    token: str
    expires_at: datetime


class CurrentOrgResponse(BaseModel):
    org_id: str
    project_id: str
