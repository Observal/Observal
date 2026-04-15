import uuid
from datetime import datetime

from pydantic import BaseModel, field_validator


class EnterpriseConfigResponse(BaseModel):
    key: str
    value: str
    model_config = {"from_attributes": True}


class EnterpriseConfigUpdate(BaseModel):
    value: str


class UserAdminResponse(BaseModel):
    id: uuid.UUID
    email: str
    name: str
    role: str
    created_at: datetime | None = None
    model_config = {"from_attributes": True}


class UserRoleUpdate(BaseModel):
    role: str


class UserCreateRequest(BaseModel):
    email: str
    name: str
    role: str = "reviewer"
    password: str | None = None

    @field_validator("email", mode="before")
    @classmethod
    def _normalize_email(cls, v: str) -> str:
        return v.strip().lower() if isinstance(v, str) else v


class UserCreateResponse(BaseModel):
    id: uuid.UUID
    email: str
    name: str
    role: str
    password: str


class AdminResetPasswordRequest(BaseModel):
    new_password: str | None = None
    generate: bool = False
