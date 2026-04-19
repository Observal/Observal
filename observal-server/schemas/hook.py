import uuid
from datetime import datetime

from pydantic import BaseModel, field_validator

from models.mcp import ListingStatus
from schemas.constants import (
    VALID_HOOK_EVENTS,
    VALID_HOOK_EXECUTION_MODES,
    VALID_HOOK_HANDLER_TYPES,
    VALID_HOOK_SCOPES,
    make_ide_list_validator,
    make_option_validator,
)


class HookSubmitRequest(BaseModel):
    name: str
    version: str
    description: str
    owner: str
    event: str
    execution_mode: str = "async"
    priority: int = 100
    handler_type: str
    handler_config: dict = {}
    input_schema: dict | None = None
    output_schema: dict | None = None
    scope: str = "agent"
    tool_filter: list[str] | None = None
    file_pattern: list[str] | None = None
    supported_ides: list[str] = []

    _validate_event = field_validator("event")(make_option_validator("event", VALID_HOOK_EVENTS))
    _validate_handler_type = field_validator("handler_type")(
        make_option_validator("handler_type", VALID_HOOK_HANDLER_TYPES)
    )
    _validate_execution_mode = field_validator("execution_mode")(
        make_option_validator("execution_mode", VALID_HOOK_EXECUTION_MODES)
    )
    _validate_scope = field_validator("scope")(make_option_validator("scope", VALID_HOOK_SCOPES))
    _validate_ides = field_validator("supported_ides")(make_ide_list_validator())


class HookListingResponse(BaseModel):
    id: uuid.UUID
    name: str
    version: str
    description: str
    owner: str
    event: str
    execution_mode: str
    priority: int
    handler_type: str
    handler_config: dict
    scope: str
    supported_ides: list[str]
    status: ListingStatus
    rejection_reason: str | None = None
    submitted_by: uuid.UUID
    created_at: datetime
    updated_at: datetime
    model_config = {"from_attributes": True}


class HookListingSummary(BaseModel):
    id: uuid.UUID
    name: str
    version: str
    description: str
    event: str
    scope: str
    owner: str
    status: ListingStatus
    model_config = {"from_attributes": True}


class HookInstallRequest(BaseModel):
    ide: str
    platform: str = ""  # e.g. "win32", "darwin", "linux" — empty = Unix default


class HookInstallResponse(BaseModel):
    listing_id: uuid.UUID
    ide: str
    config_snippet: dict
