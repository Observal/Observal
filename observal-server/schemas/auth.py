import re
import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr, field_validator

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


class InitRequest(BaseModel):
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
    created_at: datetime

    model_config = {"from_attributes": True}


class InitResponse(BaseModel):
    user: UserResponse
    access_token: str
    refresh_token: str
    expires_in: int


class CodeExchangeRequest(BaseModel):
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
