# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

import uuid
from datetime import datetime

from pydantic import BaseModel, field_validator

from models.mcp import ListingStatus
from schemas.constants import VALID_PROMPT_CATEGORIES, make_harness_list_validator, make_option_validator


class PromptSubmitRequest(BaseModel):
    name: str
    version: str
    description: str
    owner: str
    category: str
    template: str
    variables: list[dict] = []
    model_hints: dict | None = None
    tags: list[str] = []
    supported_harnesses: list[str] = []

    _validate_category = field_validator("category")(make_option_validator("category", VALID_PROMPT_CATEGORIES))
    _validate_ides = field_validator("supported_harnesses")(make_harness_list_validator())


class PromptDraftRequest(BaseModel):
    name: str
    version: str = "0.1.0"
    description: str = ""
    owner: str = ""
    category: str = "general"
    template: str = ""
    variables: list[dict] = []
    model_hints: dict | None = None
    tags: list[str] = []
    supported_harnesses: list[str] = []

    _validate_ides = field_validator("supported_harnesses")(make_harness_list_validator())


class PromptUpdateRequest(BaseModel):
    name: str | None = None
    version: str | None = None
    description: str | None = None
    owner: str | None = None
    category: str | None = None
    template: str | None = None
    variables: list[dict] | None = None
    model_hints: dict | None = None
    tags: list[str] | None = None
    supported_harnesses: list[str] | None = None


class PromptListingResponse(BaseModel):
    id: uuid.UUID
    name: str
    version: str
    description: str
    owner: str
    category: str
    template: str
    variables: list[dict]
    tags: list[str]
    supported_harnesses: list[str]
    status: ListingStatus
    rejection_reason: str | None = None
    submitted_by: uuid.UUID
    created_at: datetime
    updated_at: datetime
    download_count: int = 0
    user_permission: str | None = None

    @field_validator("user_permission", mode="before")
    @classmethod
    def _coerce_user_permission(cls, v):
        return v if isinstance(v, str) else None

    model_config = {"from_attributes": True}


class PromptListingSummary(BaseModel):
    id: uuid.UUID
    name: str
    version: str
    description: str
    category: str
    owner: str
    status: ListingStatus
    rejection_reason: str | None = None
    updated_at: datetime | None = None
    model_config = {"from_attributes": True}


class PromptRenderRequest(BaseModel):
    variables: dict[str, str] = {}


class PromptRenderResponse(BaseModel):
    listing_id: uuid.UUID
    rendered: str
