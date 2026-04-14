import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr, field_validator, model_validator

from models.user import UserRole


def _normalize_email(v: str) -> str:
    """Lowercase and strip whitespace so email lookups are case-insensitive."""
    return v.strip().lower() if isinstance(v, str) else v


class InitRequest(BaseModel):
    email: EmailStr
    name: str
    password: str | None = None

    @field_validator("email", mode="before")
    @classmethod
    def _normalize(cls, v: str) -> str:
        return _normalize_email(v)


class LoginRequest(BaseModel):
    api_key: str | None = None
    email: EmailStr | None = None
    password: str | None = None

    @field_validator("email", mode="before")
    @classmethod
    def _normalize(cls, v: str | None) -> str | None:
        return _normalize_email(v) if v is not None else v

    @model_validator(mode="after")
    def _require_credentials(self):
        has_key = bool(self.api_key)
        has_password = bool(self.email and self.password)
        if not has_key and not has_password:
            raise ValueError("Provide api_key or email+password")
        return self


class RegisterRequest(BaseModel):
    email: EmailStr
    name: str
    password: str

    @field_validator("email", mode="before")
    @classmethod
    def _normalize(cls, v: str) -> str:
        return _normalize_email(v)


class UserResponse(BaseModel):
    id: uuid.UUID
    email: str
    name: str
    role: UserRole
    created_at: datetime

    model_config = {"from_attributes": True}


class InitResponse(BaseModel):
    user: UserResponse
    api_key: str


class CodeExchangeRequest(BaseModel):
    code: str


class RequestResetRequest(BaseModel):
    email: EmailStr

    @field_validator("email", mode="before")
    @classmethod
    def _normalize(cls, v: str) -> str:
        return _normalize_email(v)


class ResetPasswordRequest(BaseModel):
    email: EmailStr
    token: str
    new_password: str

    @field_validator("email", mode="before")
    @classmethod
    def _normalize(cls, v: str) -> str:
        return _normalize_email(v)


class TokenRequest(BaseModel):
    api_key: str | None = None
    email: EmailStr | None = None
    password: str | None = None

    @field_validator("email", mode="before")
    @classmethod
    def _normalize(cls, v: str | None) -> str | None:
        return _normalize_email(v) if v is not None else v

    @model_validator(mode="after")
    def _require_credentials(self):
        has_key = bool(self.api_key)
        has_password = bool(self.email and self.password)
        if not has_key and not has_password:
            raise ValueError("Provide api_key or email+password")
        return self


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int  # seconds


class RefreshRequest(BaseModel):
    refresh_token: str


class RevokeRequest(BaseModel):
    refresh_token: str
