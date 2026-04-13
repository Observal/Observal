import uuid
from datetime import datetime

from pydantic import BaseModel, field_validator

from models.mcp import ListingStatus
from schemas.constants import VALID_MCP_CATEGORIES, make_ide_list_validator, make_option_validator


class McpSubmitRequest(BaseModel):
    git_url: str
    name: str
    version: str
    description: str = ""
    category: str
    owner: str
    supported_ides: list[str] = []
    setup_instructions: str | None = None
    changelog: str | None = None
    custom_fields: dict[str, str] = {}

    _validate_category = field_validator("category")(make_option_validator("category", VALID_MCP_CATEGORIES))
    _validate_ides = field_validator("supported_ides")(make_ide_list_validator())


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
    git_url: str
    description: str
    category: str
    owner: str
    supported_ides: list[str]
    setup_instructions: str | None
    changelog: str | None
    mcp_validated: bool = False
    status: ListingStatus
    rejection_reason: str | None = None
    submitted_by: uuid.UUID
    created_at: datetime
    updated_at: datetime
    custom_fields: list[McpCustomFieldResponse] = []
    validation_results: list[McpValidationResultResponse] = []

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

    model_config = {"from_attributes": True}


class McpInstallRequest(BaseModel):
    ide: str


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
    issues: list[str] = []
    error: str = ""


class ReviewActionRequest(BaseModel):
    reason: str | None = None
