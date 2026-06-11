# SPDX-FileCopyrightText: 2026 Aryan Iyappan <aryaniyappan2006@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Schemas for teammate invites."""

import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field, field_validator

from schemas.auth import UserResponse, _normalize_email, _validate_username


class InviteCreateRequest(BaseModel):
    # Pin the invite to an email (channel=email) or omit for a shareable link
    email: EmailStr | None = None
    role: str = "user"

    @field_validator("email", mode="before")
    @classmethod
    def _normalize(cls, v: str | None) -> str | None:
        return _normalize_email(v) if v else None


class InviteResponse(BaseModel):
    id: uuid.UUID
    email: str | None = None
    role: str
    channel: str
    status: str  # pending | accepted | expired | revoked
    created_at: datetime
    expires_at: datetime
    accepted_at: datetime | None = None

    model_config = {"from_attributes": True}

    @field_validator("role", "channel", mode="before")
    @classmethod
    def _enum_value(cls, v: object) -> object:
        return getattr(v, "value", v)


class InviteCreateResponse(InviteResponse):
    # Raw token + shareable URL, returned exactly once at creation time
    token: str
    invite_url: str


class InviteLookupResponse(BaseModel):
    """Public preview of an invite, shown on the acceptance page."""

    valid: bool
    reason: str | None = None  # set when invalid: expired | revoked | accepted | not_found
    org_name: str | None = None
    email: str | None = None
    role: str | None = None
    expires_at: datetime | None = None


class InviteAcceptRequest(BaseModel):
    token: str = Field(min_length=16, max_length=128)
    # Required for link invites; must match the pinned address for email invites
    email: EmailStr | None = None
    name: str = Field(min_length=1, max_length=255)
    username: str | None = None
    password: str

    @field_validator("email", mode="before")
    @classmethod
    def _normalize(cls, v: str | None) -> str | None:
        return _normalize_email(v) if v else None

    @field_validator("username", mode="before")
    @classmethod
    def _validate_un(cls, v: str | None) -> str | None:
        return _validate_username(v)


class InviteAcceptResponse(BaseModel):
    user: UserResponse
    access_token: str
    refresh_token: str
    expires_in: int
