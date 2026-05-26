# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-FileCopyrightText: 2026 Lokesh Selvam <lokeshselvam7025@gmail.com>
# SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

import uuid
from datetime import datetime

from pydantic import BaseModel, field_validator

from models.mcp import ListingStatus
from schemas.constants import VALID_SKILL_TASK_TYPES, make_ide_list_validator, make_option_validator


class SkillSubmitRequest(BaseModel):
    name: str
    version: str
    description: str
    owner: str
    skill_path: str = "/"
    git_url: str | None = None
    git_ref: str | None = None
    skill_md_content: str | None = None
    delivery_mode: str = "git_fetch"
    script_content: str | None = None
    script_filename: str | None = None
    target_agents: list[str] = []
    task_type: str
    slash_command: str | None = None
    supported_ides: list[str] = []

    _validate_task_type = field_validator("task_type")(make_option_validator("task_type", VALID_SKILL_TASK_TYPES))
    _validate_ides = field_validator("supported_ides")(make_ide_list_validator())


class SkillDraftRequest(BaseModel):
    name: str
    version: str = "0.1.0"
    description: str = ""
    owner: str = ""
    skill_path: str = "/"
    git_url: str | None = None
    git_ref: str | None = None
    skill_md_content: str | None = None
    delivery_mode: str = "git_fetch"
    script_content: str | None = None
    script_filename: str | None = None
    target_agents: list[str] = []
    task_type: str = "general"
    slash_command: str | None = None
    supported_ides: list[str] = []

    _validate_ides = field_validator("supported_ides")(make_ide_list_validator())


class SkillUpdateRequest(BaseModel):
    name: str | None = None
    version: str | None = None
    description: str | None = None
    owner: str | None = None
    skill_path: str | None = None
    git_url: str | None = None
    git_ref: str | None = None
    skill_md_content: str | None = None
    delivery_mode: str | None = None
    script_content: str | None = None
    script_filename: str | None = None
    target_agents: list[str] | None = None
    task_type: str | None = None
    slash_command: str | None = None
    supported_ides: list[str] | None = None


class SkillListingResponse(BaseModel):
    id: uuid.UUID
    name: str
    version: str
    description: str
    owner: str
    task_type: str
    target_agents: list[str]
    supported_ides: list[str]
    skill_path: str
    git_url: str | None = None
    git_ref: str | None = None
    skill_md_content: str | None = None
    delivery_mode: str = "git_fetch"
    script_content: str | None = None
    script_filename: str | None = None
    validated: bool = False
    slash_command: str | None = None
    status: ListingStatus
    rejection_reason: str | None = None
    submitted_by: uuid.UUID
    created_at: datetime
    updated_at: datetime
    user_permission: str | None = None

    @field_validator("user_permission", mode="before")
    @classmethod
    def _coerce_user_permission(cls, v):
        return v if isinstance(v, str) else None

    model_config = {"from_attributes": True}


class SkillListingSummary(BaseModel):
    id: uuid.UUID
    name: str
    version: str
    description: str
    task_type: str
    owner: str
    target_agents: list[str]
    status: ListingStatus
    rejection_reason: str | None = None
    model_config = {"from_attributes": True}


class SkillInstallRequest(BaseModel):
    ide: str
    scope: str = "project"


class SkillInstallResponse(BaseModel):
    listing_id: uuid.UUID
    ide: str
    config_snippet: dict
