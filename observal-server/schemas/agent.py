import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from models.agent import AgentStatus

VALID_COMPONENT_TYPES = {"mcp", "skill", "hook", "prompt", "sandbox"}


class GoalSectionRequest(BaseModel):
    name: str
    description: str | None = None
    grounding_required: bool = False


class GoalTemplateRequest(BaseModel):
    description: str
    sections: list[GoalSectionRequest] = Field(min_length=1)


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


class AgentCreateRequest(BaseModel):
    name: str
    version: str
    description: str = ""
    owner: str
    prompt: str = ""
    model_name: str
    model_config_json: dict = {}
    supported_ides: list[str] = []
    mcp_server_ids: list[uuid.UUID] = []  # kept for backwards compat
    components: list[ComponentRef] = []  # new: all component types
    external_mcps: list[ExternalMcp] = []
    goal_template: GoalTemplateRequest


class AgentUpdateRequest(BaseModel):
    name: str | None = None
    version: str | None = None
    description: str | None = None
    owner: str | None = None
    prompt: str | None = None
    model_name: str | None = None
    model_config_json: dict | None = None
    supported_ides: list[str] | None = None
    mcp_server_ids: list[uuid.UUID] | None = None  # kept for backwards compat
    components: list[ComponentRef] | None = None  # new: all component types
    external_mcps: list[ExternalMcp] | None = None
    goal_template: GoalTemplateRequest | None = None


class GoalSectionResponse(BaseModel):
    name: str
    description: str | None
    grounding_required: bool
    order: int
    model_config = {"from_attributes": True}


class GoalTemplateResponse(BaseModel):
    description: str
    sections: list[GoalSectionResponse] = []
    model_config = {"from_attributes": True}


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
    external_mcps: list = []
    supported_ides: list[str]
    status: AgentStatus
    created_by: uuid.UUID
    created_at: datetime
    updated_at: datetime
    mcp_links: list[McpLinkResponse] = []
    component_links: list[ComponentLinkResponse] = []
    goal_template: GoalTemplateResponse | None = None

    model_config = {"from_attributes": True}


class AgentSummary(BaseModel):
    id: uuid.UUID
    name: str
    version: str
    description: str
    owner: str
    model_name: str
    supported_ides: list[str]
    status: AgentStatus
    download_count: int = 0
    average_rating: float | None = None
    component_count: int = 0
    created_at: datetime | None = None
    updated_at: datetime | None = None
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


class AgentInstallResponse(BaseModel):
    agent_id: uuid.UUID
    ide: str
    config_snippet: dict
