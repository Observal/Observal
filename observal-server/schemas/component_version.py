# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Shared Pydantic schemas for component version API endpoints."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class VersionPublishRequest(BaseModel):
    version: str
    description: str
    changelog: str | None = None
    supported_ides: list[str] = []
    extra: dict | None = None


class VersionReviewRequest(BaseModel):
    action: Literal["approve", "reject"]
    reason: str | None = None
