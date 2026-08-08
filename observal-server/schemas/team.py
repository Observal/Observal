# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: Apache-2.0

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from models.team import TeamRole


class TeamCreateRequest(BaseModel):
    name: str
    handle: str | None = None
    description: str | None = None
    visibility: Literal["public", "private"] = "public"


class TeamUpdateRequest(BaseModel):
    name: str | None = None
    description: str | None = None


class TeamVisibilityUpdateRequest(BaseModel):
    visibility: Literal["public", "private"]


class TeamResponse(BaseModel):
    id: uuid.UUID
    name: str
    handle: str
    description: str | None = None
    visibility: str = "public"
    is_personal: bool = False
    role: str | None = None
    member_count: int | None = None
    created_at: datetime | None = None
    model_config = ConfigDict(from_attributes=True)


class TeamMemberResponse(BaseModel):
    id: uuid.UUID
    email: str
    username: str | None = None
    name: str | None = None
    role: str
    model_config = ConfigDict(from_attributes=True)


class TeamMemberUpsertRequest(BaseModel):
    email: str | None = None
    username: str | None = None
    user_id: uuid.UUID | None = None
    role: TeamRole = TeamRole.member

    @model_validator(mode="after")
    def _require_identifier(self) -> "TeamMemberUpsertRequest":
        if not (self.email or self.username or self.user_id):
            raise ValueError("One of email, username, or user_id is required")
        return self


class TeamJoinRequestCreate(BaseModel):
    message: str | None = Field(default=None, max_length=500)


class TeamJoinDecisionRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=500)


class TeamJoinRequestResponse(BaseModel):
    id: uuid.UUID
    team_id: uuid.UUID
    user_id: uuid.UUID
    email: str | None = None
    username: str | None = None
    name: str | None = None
    status: str
    message: str | None = None
    decided_by: uuid.UUID | None = None
    decided_by_username: str | None = None
    decided_at: datetime | None = None
    decision_reason: str | None = None
    created_at: datetime | None = None
    model_config = ConfigDict(from_attributes=True)
