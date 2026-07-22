# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: Apache-2.0

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from models.team import TeamRole


class TeamCreateRequest(BaseModel):
    name: str
    handle: str | None = None
    description: str | None = None


class TeamUpdateRequest(BaseModel):
    name: str | None = None
    description: str | None = None


class TeamResponse(BaseModel):
    id: uuid.UUID
    name: str
    handle: str
    description: str | None = None
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
