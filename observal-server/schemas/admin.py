# SPDX-FileCopyrightText: 2026 Subramania Raja <dhanpraja231@gmail.com>
# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-FileCopyrightText: 2026 Lokesh Selvam <lokeshselvam7025@gmail.com>
# SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

import uuid
from datetime import datetime

from pydantic import BaseModel, field_validator


class EnterpriseConfigResponse(BaseModel):
    key: str
    value: str
    is_sensitive: bool = False
    is_set: bool = False
    model_config = {"from_attributes": True}


class EnterpriseConfigUpdate(BaseModel):
    value: str


class SettingRevokedResponse(BaseModel):
    revoked: str
    message: str


class UserAdminResponse(BaseModel):
    id: uuid.UUID
    email: str
    username: str | None = None
    name: str
    role: str
    department: str | None = None
    created_at: datetime | None = None
    model_config = {"from_attributes": True}


class UserRoleUpdate(BaseModel):
    role: str


class UserDepartmentUpdate(BaseModel):
    department: str | None = None


class UserCreateRequest(BaseModel):
    email: str
    name: str
    username: str | None = None
    role: str = "reviewer"
    password: str | None = None

    @field_validator("email", mode="before")
    @classmethod
    def _normalize_email(cls, v: str) -> str:
        return v.strip().lower() if isinstance(v, str) else v


class UserCreateResponse(BaseModel):
    id: uuid.UUID
    email: str
    username: str | None = None
    name: str
    role: str
    password: str


class AdminResetPasswordRequest(BaseModel):
    new_password: str | None = None
    generate: bool = False
