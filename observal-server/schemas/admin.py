import uuid
from datetime import datetime

from pydantic import BaseModel


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
    role: str = "developer"


class UserCreateResponse(BaseModel):
    id: uuid.UUID
    email: str
    name: str
    role: str
    api_key: str


class AdminResetPasswordRequest(BaseModel):
    new_password: str
