# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-FileCopyrightText: 2026 Lokesh Selvam <lokeshselvam7025@gmail.com>
# SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
# SPDX-FileCopyrightText: 2026 tsitu0 <tomsitu0102@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

import uuid
from datetime import datetime

from pydantic import BaseModel, field_validator

from models.mcp import ListingStatus
from schemas.constants import VALID_SKILL_TASK_TYPES, make_harness_list_validator, make_option_validator
from schemas.skill_commands import normalize_slash_command


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
    supported_harnesses: list[str] = []

    _validate_task_type = field_validator("task_type")(make_option_validator("task_type", VALID_SKILL_TASK_TYPES))
    _validate_ides = field_validator("supported_harnesses")(make_harness_list_validator())

    @field_validator("slash_command")
    @classmethod
    def _validate_slash_command(cls, v: str | None) -> str | None:
        return normalize_slash_command(v)


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
    supported_harnesses: list[str] = []

    _validate_ides = field_validator("supported_harnesses")(make_harness_list_validator())

    @field_validator("slash_command")
    @classmethod
    def _validate_slash_command(cls, v: str | None) -> str | None:
        return normalize_slash_command(v)


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
    supported_harnesses: list[str] | None = None

    @field_validator("slash_command")
    @classmethod
    def _validate_slash_command(cls, v: str | None) -> str | None:
        return normalize_slash_command(v)


class SkillListingResponse(BaseModel):
    id: uuid.UUID
    name: str
    version: str
    description: str
    owner: str
    task_type: str
    target_agents: list[str]
    supported_harnesses: list[str]
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
    download_count: int = 0
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
    harness: str
    scope: str = "project"
    version: str | None = None  # Specific version to install (None = latest)


class SkillInstallResponse(BaseModel):
    listing_id: uuid.UUID
    harness: str
    config_snippet: dict
    warnings: list[str] = []
