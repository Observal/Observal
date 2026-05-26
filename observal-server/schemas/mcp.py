# SPDX-FileCopyrightText: 2026 Subramania Raja <dhanpraja231@gmail.com>
# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

import uuid
from datetime import datetime

from pydantic import BaseModel, Field, field_validator, model_validator

from models.mcp import ListingStatus
from schemas.constants import VALID_MCP_CATEGORIES, VALID_MCP_FRAMEWORKS, make_ide_list_validator, make_option_validator


class McpEnvVar(BaseModel):
    name: str
    description: str = ""
    required: bool = True


class McpHeader(BaseModel):
    name: str
    description: str = ""
    required: bool = True


def _coerce_env_vars(v):
    """Coerce None → [] so DB NULLs don't break serialization."""
    return v or []


class ClientAnalysis(BaseModel):
    """Analysis results produced client-side (CLI local clone)."""

    tools: list[dict] = []
    issues: list[str] = []
    framework: str = ""
    entry_point: str = ""
    command: str | None = None
    args: list[str] | None = None
    docker_image: str | None = None


class McpSubmitRequest(BaseModel):
    git_url: str | None = None
    name: str
    version: str
    description: str = Field(min_length=1)
    category: str
    owner: str
    framework: str | None = None
    docker_image: str | None = None
    command: str | None = None
    args: list[str] | None = None
    url: str | None = None
    headers: list[McpHeader] | None = None
    auto_approve: list[str] | None = None
    transport: str | None = None
    supported_ides: list[str] = []
    environment_variables: list[McpEnvVar] = []
    setup_instructions: str | None = None
    changelog: str | None = None
    custom_fields: dict[str, str] = {}
    client_analysis: ClientAnalysis | None = None

    _validate_category = field_validator("category")(make_option_validator("category", VALID_MCP_CATEGORIES))

    @field_validator("framework")
    @classmethod
    def _validate_framework(cls, v: str | None) -> str | None:
        if v is not None and v not in VALID_MCP_FRAMEWORKS:
            raise ValueError(f"Invalid framework '{v}'. Valid options: {', '.join(VALID_MCP_FRAMEWORKS)}")
        return v

    _validate_ides = field_validator("supported_ides")(make_ide_list_validator())

    @model_validator(mode="after")
    def _require_source(self):
        if not self.git_url and not self.command and not self.url:
            raise ValueError("At least one of git_url, command, or url must be provided")
        return self


class McpDraftRequest(BaseModel):
    name: str
    version: str = "0.1.0"
    description: str = ""
    category: str = "other"
    owner: str = ""
    git_url: str | None = None
    framework: str | None = None
    docker_image: str | None = None
    command: str | None = None
    args: list[str] | None = None
    url: str | None = None
    headers: list[McpHeader] | None = None
    auto_approve: list[str] | None = None
    transport: str | None = None
    supported_ides: list[str] = []
    environment_variables: list[McpEnvVar] = []
    setup_instructions: str | None = None
    changelog: str | None = None
    client_analysis: ClientAnalysis | None = None

    _validate_ides = field_validator("supported_ides")(make_ide_list_validator())


class McpUpdateRequest(BaseModel):
    name: str | None = None
    version: str | None = None
    description: str | None = None
    category: str | None = None
    owner: str | None = None
    git_url: str | None = None
    framework: str | None = None
    docker_image: str | None = None
    command: str | None = None
    args: list[str] | None = None
    url: str | None = None
    headers: list[McpHeader] | None = None
    auto_approve: list[str] | None = None
    transport: str | None = None
    supported_ides: list[str] | None = None
    environment_variables: list[McpEnvVar] | None = None
    setup_instructions: str | None = None
    changelog: str | None = None


class McpCustomFieldResponse(BaseModel):
    field_name: str
    field_value: str
    model_config = {"from_attributes": True}


class McpValidationResultResponse(BaseModel):
    stage: str
    passed: bool
    details: str | None
    run_at: datetime
    model_config = {"from_attributes": True}


class McpListingResponse(BaseModel):
    id: uuid.UUID
    name: str
    version: str
    git_url: str | None = None
    description: str
    category: str
    owner: str
    supported_ides: list[str]
    environment_variables: list[McpEnvVar] = []
    setup_instructions: str | None
    changelog: str | None
    framework: str | None = None
    docker_image: str | None = None
    command: str | None = None
    args: list[str] | None = None
    url: str | None = None
    headers: list[McpHeader] | None = None
    auto_approve: list[str] | None = None
    mcp_validated: bool = False

    _coerce_env = field_validator("environment_variables", mode="before")(_coerce_env_vars)
    status: ListingStatus
    rejection_reason: str | None = None
    submitted_by: uuid.UUID
    created_at: datetime
    updated_at: datetime
    custom_fields: list[McpCustomFieldResponse] = []
    validation_results: list[McpValidationResultResponse] = []
    user_permission: str | None = None

    @field_validator("user_permission", mode="before")
    @classmethod
    def _coerce_user_permission(cls, v):
        return v if isinstance(v, str) else None

    model_config = {"from_attributes": True}


class McpListingSummary(BaseModel):
    id: uuid.UUID
    name: str
    version: str
    description: str
    category: str
    owner: str
    supported_ides: list[str]
    status: ListingStatus
    rejection_reason: str | None = None

    model_config = {"from_attributes": True}


class McpInstallRequest(BaseModel):
    ide: str
    env_values: dict[str, str] = {}
    header_values: dict[str, str] = {}


class McpInstallResponse(BaseModel):
    listing_id: uuid.UUID
    ide: str
    config_snippet: dict


class McpAnalyzeRequest(BaseModel):
    git_url: str


class McpAnalyzeResponse(BaseModel):
    name: str
    description: str
    version: str
    tools: list[dict]
    environment_variables: list[McpEnvVar] = []
    issues: list[str] = []
    error: str = ""
    command: str | None = None
    args: list[str] | None = None
    framework: str | None = None
    docker_image: str | None = None

    _coerce_env = field_validator("environment_variables", mode="before")(_coerce_env_vars)


class ReviewActionRequest(BaseModel):
    reason: str | None = None
