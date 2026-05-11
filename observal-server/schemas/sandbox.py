# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

import uuid
from datetime import datetime

from pydantic import BaseModel, field_validator

from models.mcp import ListingStatus
from schemas.constants import (
    VALID_SANDBOX_NETWORK_POLICIES,
    VALID_SANDBOX_RUNTIME_TYPES,
    make_ide_list_validator,
    make_option_validator,
)


class SandboxSubmitRequest(BaseModel):
    name: str
    version: str
    description: str
    owner: str
    runtime_type: str
    image: str
    dockerfile_url: str | None = None
    resource_limits: dict = {}
    network_policy: str = "none"
    allowed_mounts: list[str] = []
    env_vars: dict = {}
    entrypoint: str | None = None
    supported_ides: list[str] = []

    _validate_runtime_type = field_validator("runtime_type")(
        make_option_validator("runtime_type", VALID_SANDBOX_RUNTIME_TYPES)
    )
    _validate_network_policy = field_validator("network_policy")(
        make_option_validator("network_policy", VALID_SANDBOX_NETWORK_POLICIES)
    )
    _validate_ides = field_validator("supported_ides")(make_ide_list_validator())


class SandboxDraftRequest(BaseModel):
    name: str
    version: str = "0.1.0"
    description: str = ""
    owner: str = ""
    runtime_type: str = "docker"
    image: str = ""
    dockerfile_url: str | None = None
    resource_limits: dict = {}
    network_policy: str = "none"
    allowed_mounts: list[str] = []
    env_vars: dict = {}
    entrypoint: str | None = None
    supported_ides: list[str] = []

    _validate_ides = field_validator("supported_ides")(make_ide_list_validator())


class SandboxUpdateRequest(BaseModel):
    name: str | None = None
    version: str | None = None
    description: str | None = None
    owner: str | None = None
    runtime_type: str | None = None
    image: str | None = None
    dockerfile_url: str | None = None
    resource_limits: dict | None = None
    network_policy: str | None = None
    allowed_mounts: list[str] | None = None
    env_vars: dict | None = None
    entrypoint: str | None = None
    supported_ides: list[str] | None = None


class SandboxListingResponse(BaseModel):
    id: uuid.UUID
    name: str
    version: str
    description: str
    owner: str
    runtime_type: str
    image: str
    resource_limits: dict
    network_policy: str
    supported_ides: list[str]
    status: ListingStatus
    rejection_reason: str | None = None
    submitted_by: uuid.UUID
    created_at: datetime
    updated_at: datetime
    model_config = {"from_attributes": True}


class SandboxListingSummary(BaseModel):
    id: uuid.UUID
    name: str
    version: str
    description: str
    runtime_type: str
    owner: str
    supported_ides: list[str]
    status: ListingStatus
    rejection_reason: str | None = None
    model_config = {"from_attributes": True}


class SandboxInstallRequest(BaseModel):
    ide: str


class SandboxInstallResponse(BaseModel):
    listing_id: uuid.UUID
    ide: str
    config_snippet: dict
