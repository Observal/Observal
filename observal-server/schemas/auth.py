# SPDX-FileCopyrightText: 2026 Subramania Raja <dhanpraja231@gmail.com>
# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-FileCopyrightText: 2026 Lokesh Selvam <lokeshselvam7025@gmail.com>
# SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

import re
import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field, field_validator

from models.user import UserRole

USERNAME_RE = re.compile(r"^[a-z0-9][a-z0-9\-]{1,30}[a-z0-9]$")


def _normalize_email(v: str) -> str:
    """Lowercase and strip whitespace so email lookups are case-insensitive."""
    return v.strip().lower() if isinstance(v, str) else v


def _validate_username(v: str | None) -> str | None:
    if v is None:
        return None
    v = v.strip().lower()
    if not USERNAME_RE.match(v):
        raise ValueError("Username must be 3-32 chars, lowercase alphanumeric and hyphens only")
    return v


class UtmFields(BaseModel):
    """First-touch acquisition attribution, captured by the web app on first
    load and forwarded with signup requests. Used only for product analytics
    (user_signed_up event); never persisted to the users table."""

    utm_source: str | None = Field(default=None, max_length=255)
    utm_medium: str | None = Field(default=None, max_length=255)
    utm_campaign: str | None = Field(default=None, max_length=255)


class InitRequest(UtmFields):
    email: EmailStr
    name: str
    username: str | None = None
    password: str | None = None

    @field_validator("email", mode="before")
    @classmethod
    def _normalize(cls, v: str) -> str:
        return _normalize_email(v)

    @field_validator("username", mode="before")
    @classmethod
    def _validate_un(cls, v: str | None) -> str | None:
        return _validate_username(v)


class LoginRequest(BaseModel):
    email: str
    password: str

    @field_validator("email", mode="before")
    @classmethod
    def _normalize(cls, v: str) -> str:
        return v.strip().lower() if isinstance(v, str) else v


class UserResponse(BaseModel):
    id: uuid.UUID
    email: str
    username: str | None = None
    name: str
    role: UserRole
    org_id: uuid.UUID | None = None
    avatar_url: str | None = None
    created_at: datetime
    # Populated from the org join in get_current_user; consumed by the web
    # app to suppress product analytics for trace-private orgs.
    trace_privacy: bool = False

    model_config = {"from_attributes": True}


class InitResponse(BaseModel):
    user: UserResponse
    access_token: str
    refresh_token: str
    expires_in: int


class CodeExchangeRequest(UtmFields):
    code: str


class TokenRequest(BaseModel):
    email: str
    password: str

    @field_validator("email", mode="before")
    @classmethod
    def _normalize(cls, v: str) -> str:
        return v.strip().lower() if isinstance(v, str) else v


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int  # seconds


class RefreshRequest(BaseModel):
    refresh_token: str


class RevokeRequest(BaseModel):
    refresh_token: str


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str

    @field_validator("new_password")
    @classmethod
    def _validate_new(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters")
        return v


class UsernameUpdateRequest(BaseModel):
    username: str

    @field_validator("username", mode="before")
    @classmethod
    def _validate_un(cls, v: str) -> str:
        result = _validate_username(v)
        if result is None:
            raise ValueError("Username is required")
        return result


# ── Device Authorization Grant (RFC 8628) ─────────────────


class DeviceAuthRequest(BaseModel):
    client_id: str | None = None


class DeviceAuthResponse(BaseModel):
    device_code: str
    user_code: str
    verification_uri: str
    verification_uri_complete: str
    expires_in: int
    interval: int


class DeviceTokenRequest(BaseModel):
    device_code: str
    grant_type: str


class DeviceConfirmRequest(BaseModel):
    user_code: str


class LogoutRequest(BaseModel):
    refresh_token: str | None = None
