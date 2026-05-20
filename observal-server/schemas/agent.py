# SPDX-FileCopyrightText: 2026 Apoorv Garg <apoorvgarg.21@gmail.com>
# SPDX-FileCopyrightText: 2026 Aryan Iyappan <aryaniyappan2006@gmail.com>
# SPDX-FileCopyrightText: 2026 Subramania Raja <dhanpraja231@gmail.com>
# SPDX-FileCopyrightText: 2026 Harishankar <harishankar0301@gmail.com>
# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-FileCopyrightText: 2026 Lokesh Selvam <lokeshselvam7025@gmail.com>
# SPDX-FileCopyrightText: 2026 Naraen Rammoorthi <naraen13@gmail.com>
# SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from config import settings
from models.agent import AgentStatus, AgentVisibility
from schemas.constants import AGENT_NAME_REGEX, make_name_validator
from services.versioning import validate_semver

_DEFAULT_VISIBILITY = AgentVisibility.public if settings.DEPLOYMENT_MODE == "local" else AgentVisibility.private

VALID_COMPONENT_TYPES = {"mcp", "skill", "hook", "prompt", "sandbox"}


class ExternalMcp(BaseModel):
    name: str
    command: str = "npx"
    args: list[str] = []
    env: dict[str, str] = {}
    url: str | None = None  # source URL for reference


ComponentType = Literal["mcp", "skill", "hook", "prompt", "sandbox"]


class ComponentRef(BaseModel):
    """Reference to a registry component to include in an agent."""

    component_type: ComponentType
    component_id: uuid.UUID
    config_override: dict | None = None


class TeamAccessRequest(BaseModel):
    group_name: str = Field(min_length=1, max_length=255)
    permission: Literal["view", "edit"]


class TeamAccessResponse(BaseModel):
    group_name: str
    permission: str
    model_config = {"from_attributes": True}


class AgentCreateRequest(BaseModel):
    name: str
    version: str
    description: str = ""
    owner: str
    prompt: str = ""
    model_name: str
    model_config_json: dict = {}
    models_by_ide: dict[str, str] = {}
    supported_ides: list[str] = []
    mcp_server_ids: list[uuid.UUID] = []  # kept for backwards compat
    components: list[ComponentRef] = []  # new: all component types
    external_mcps: list[ExternalMcp] = []
    visibility: AgentVisibility = _DEFAULT_VISIBILITY
    team_accesses: list[TeamAccessRequest] = []

    _validate_name = field_validator("name")(make_name_validator("name"))

    @field_validator("version")
    @classmethod
    def _validate_version(cls, v: str) -> str:
        if not validate_semver(v):
            raise ValueError(f"Invalid version '{v}'. Must be semver format: x.y.z (e.g. 1.0.0)")
        return v

    @field_validator("prompt", mode="after")
    @classmethod
    def _require_prompt_or_prompt_component(cls, v: str, info) -> str:
        components = (info.data or {}).get("components", [])
        has_prompt_component = any(c.component_type == "prompt" for c in components)
        if not v and not has_prompt_component:
            raise ValueError("A system prompt is required. Either set a custom prompt or add a Prompt component.")
        return v


class AgentUpdateRequest(BaseModel):
    name: str | None = None
    version: str | None = None
    version_bump_type: Literal["patch", "minor", "major"] | None = None
    description: str | None = None
    owner: str | None = None
    prompt: str | None = None
    model_name: str | None = None
    model_config_json: dict | None = None
    models_by_ide: dict[str, str] | None = None
    supported_ides: list[str] | None = None
    mcp_server_ids: list[uuid.UUID] | None = None  # kept for backwards compat
    components: list[ComponentRef] | None = None  # new: all component types
    external_mcps: list[ExternalMcp] | None = None
    visibility: AgentVisibility | None = None
    team_accesses: list[TeamAccessRequest] | None = None

    @field_validator("name", mode="before")
    @classmethod
    def _validate_name(cls, v: str | None) -> str | None:
        if v is None:
            return v
        if len(v) > 64:
            raise ValueError("name must be at most 64 characters")
        if not AGENT_NAME_REGEX.match(v):
            raise ValueError(
                f"Invalid name '{v}'. "
                "Must start with a letter or digit and contain only lowercase letters, digits, hyphens, and underscores."
            )
        return v

    @field_validator("version", mode="before")
    @classmethod
    def _validate_version(cls, v: str | None) -> str | None:
        if v is not None and not validate_semver(v):
            raise ValueError(f"Invalid version '{v}'. Must be semver format: x.y.z (e.g. 1.0.0)")
        return v


class McpLinkResponse(BaseModel):
    mcp_listing_id: uuid.UUID
    mcp_name: str
    order: int
    model_config = {"from_attributes": True}


class ComponentLinkResponse(BaseModel):
    """A component attached to an agent."""

    component_type: str
    component_id: uuid.UUID
    component_name: str = ""
    version_ref: str
    order: int
    config_override: dict | None = None
    model_config = {"from_attributes": True}


class AgentResponse(BaseModel):
    id: uuid.UUID
    name: str
    version: str
    description: str
    owner: str
    prompt: str
    model_name: str
    model_config_json: dict
    models_by_ide: dict[str, str] = {}
    external_mcps: list = []
    supported_ides: list[str]
    required_ide_features: list[str] = []
    inferred_supported_ides: list[str] = []
    status: AgentStatus
    rejection_reason: str | None = None
    created_by: uuid.UUID
    created_by_email: str = ""
    created_by_username: str | None = None
    created_at: datetime
    updated_at: datetime
    mcp_links: list[McpLinkResponse] = []
    component_links: list[ComponentLinkResponse] = []
    visibility: AgentVisibility
    team_accesses: list[TeamAccessResponse] = []
    user_permission: str | None = None
    latest_approved_version: str | None = None
    latest_version: str | None = None

    model_config = {"from_attributes": True}


class AgentSummary(BaseModel):
    id: uuid.UUID
    name: str
    version: str
    description: str
    owner: str
    model_name: str
    supported_ides: list[str]
    required_ide_features: list[str] = []
    inferred_supported_ides: list[str] = []
    status: AgentStatus
    rejection_reason: str | None = None
    download_count: int = 0
    average_rating: float | None = None
    component_count: int = 0
    created_by: uuid.UUID | None = None
    created_by_email: str = ""
    created_by_username: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    components_ready: bool = True
    blocking_components: list = []
    visibility: AgentVisibility
    model_config = {"from_attributes": True}


class AgentValidateRequest(BaseModel):
    components: list[ComponentRef] = []


class ValidationIssue(BaseModel):
    severity: Literal["error", "warning"]
    component_type: str | None = None
    component_id: uuid.UUID | None = None
    message: str


class ValidationResult(BaseModel):
    valid: bool
    issues: list[ValidationIssue] = []


class AgentInstallRequest(BaseModel):
    ide: str
    env_values: dict[str, dict[str, str]] = {}  # {mcp_listing_id: {VAR: value}}
    # IDE-specific install options (e.g. scope, model, tools, color for Claude Code)
    options: dict = {}
    platform: str = ""  # e.g. "win32", "darwin", "linux" — empty = Unix default


class AgentInstallResponse(BaseModel):
    agent_id: uuid.UUID
    ide: str
    config_snippet: dict
    warnings: list[str] = []


class AgentVersionCreateRequest(BaseModel):
    version: str
    description: str = ""
    prompt: str = ""
    model_name: str
    model_config_json: dict = {}
    models_by_ide: dict[str, str] = {}
    external_mcps: list[ExternalMcp] = []
    supported_ides: list[str] = []
    components: list[ComponentRef] = []
    yaml_snapshot: str | None = None
    is_prerelease: bool = False
    save_as_draft: bool = False

    @field_validator("version")
    @classmethod
    def _validate_version(cls, v: str) -> str:
        if not validate_semver(v):
            raise ValueError(f"Invalid version '{v}'. Must be semver format: x.y.z (e.g. 1.0.0)")
        return v


class AgentVersionReviewRequest(BaseModel):
    action: Literal["approve", "reject"]
    reason: str | None = None
