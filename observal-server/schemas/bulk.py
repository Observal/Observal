# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

from __future__ import annotations

import uuid  # noqa: TC003 — needed at runtime by Pydantic

from pydantic import BaseModel, Field


class BulkAgentItem(BaseModel):
    """Single agent in a bulk create request. Extends AgentCreateRequest fields with relaxed defaults."""

    name: str
    version: str = "1.0.0"
    description: str = ""
    owner: str = ""
    prompt: str = ""
    model_name: str = "claude-sonnet-4"
    model_config_json: dict = {}
    supported_ides: list[str] = []
    components: list[dict] = []  # [{component_type, component_id}]
    external_mcps: list[dict] = []


class BulkAgentRequest(BaseModel):
    agents: list[BulkAgentItem] = Field(min_length=1, max_length=50)
    dry_run: bool = False


class BulkResultItem(BaseModel):
    name: str
    status: str  # "created", "skipped", "error"
    agent_id: uuid.UUID | None = None
    error: str | None = None


class BulkResult(BaseModel):
    total: int
    created: int
    skipped: int
    errors: int
    dry_run: bool
    results: list[BulkResultItem]
