# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-FileCopyrightText: 2026 Naraen Rammoorthi <naraen13@gmail.com>
# SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

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
    scope: str = "agent"
    tool_filter: list[str] | None = None
    supported_ides: list[str] = []
    # Script delivery
    script_content: str | None = None
    script_filename: str | None = None
    # Source tracking
    source_url: str | None = None
    source_ref: str | None = None
    source_path: str | None = None
    # Requirements
    requirements: list[str] | None = None

    _validate_event = field_validator("event")(make_option_validator("event", VALID_HOOK_EVENTS))
    _validate_handler_type = field_validator("handler_type")(
        make_option_validator("handler_type", VALID_HOOK_HANDLER_TYPES)
    )
    _validate_execution_mode = field_validator("execution_mode")(
        make_option_validator("execution_mode", VALID_HOOK_EXECUTION_MODES)
    )
    _validate_scope = field_validator("scope")(make_option_validator("scope", VALID_HOOK_SCOPES))
    _validate_ides = field_validator("supported_ides")(make_ide_list_validator())


class HookDraftRequest(BaseModel):
    name: str
    version: str = "0.1.0"
    description: str = ""
    owner: str = ""
    event: str = "PreToolUse"
    execution_mode: str = "async"
    priority: int = 100
    handler_type: str = "command"
    handler_config: dict = {}
    scope: str = "agent"
    tool_filter: list[str] | None = None
    supported_ides: list[str] = []
    script_content: str | None = None
    script_filename: str | None = None
    source_url: str | None = None
    source_ref: str | None = None
    source_path: str | None = None
    requirements: list[str] | None = None

    _validate_ides = field_validator("supported_ides")(make_ide_list_validator())


class HookUpdateRequest(BaseModel):
    name: str | None = None
    version: str | None = None
    description: str | None = None
    owner: str | None = None
    event: str | None = None
    execution_mode: str | None = None
    priority: int | None = None
    handler_type: str | None = None
    handler_config: dict | None = None
    scope: str | None = None
    tool_filter: list[str] | None = None
    supported_ides: list[str] | None = None
    script_content: str | None = None
    script_filename: str | None = None
    source_url: str | None = None
    source_ref: str | None = None
    source_path: str | None = None
    requirements: list[str] | None = None


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
    rejection_reason: str | None = None
    model_config = {"from_attributes": True}


class HookInstallRequest(BaseModel):
    ide: str
    platform: str = ""  # e.g. "win32", "darwin", "linux" — empty = Unix default


class HookFileEntry(BaseModel):
    path: str
    content: str
    executable: bool = False


class HookInstallResponse(BaseModel):
    listing_id: uuid.UUID
    ide: str
    config_snippet: dict
    config_path: str = ""
    files: list[HookFileEntry] = []
    requirements: list[str] = []
    source_fetch: dict | None = None
    notes: list[str] = []
