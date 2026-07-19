# SPDX-FileCopyrightText: 2026 Vishnu Muthiah <vishnu.muthiah04@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""Preview endpoint - generates full harness config without persisting an agent."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends
from loguru import logger as optic
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from api.deps import get_current_user, get_db
from models.hook import HookListing
from models.mcp import McpListing
from models.prompt import PromptListing
from models.skill import SkillListing
from observal_shared.harness_registry import HARNESS_REGISTRY
from services.harness import generate_agent_config

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from models.user import User

router = APIRouter(prefix="/api/v1/agents", tags=["agents"])

_VALID_HARNESSES = set(HARNESS_REGISTRY.keys())
_MAX_COMPONENTS = 20
_MAX_NAME_LEN = 100
_MAX_PROMPT_LEN = 50_000


# ── Request / response schemas ────────────────────────────────


class PreviewComponentRef(BaseModel):
    component_type: str = Field(pattern=r"^(mcp|skill|hook|prompt)$")
    component_id: uuid.UUID


class PreviewConfigRequest(BaseModel):
    name: str = Field(max_length=_MAX_NAME_LEN, default="untitled")
    description: str = Field(max_length=1000, default="")
    prompt: str = Field(max_length=_MAX_PROMPT_LEN, default="")
    model_name: str = Field(max_length=100, default="")
    components: list[PreviewComponentRef] = Field(default_factory=list, max_length=_MAX_COMPONENTS)
    target_harnesses: list[str] = Field(default_factory=list, max_length=9)


class PreviewConfigResponse(BaseModel):
    configs: dict[str, dict[str, str]]


# ── Transient agent-like dataclass ────────────────────────────


@dataclass
class _TransientComponent:
    component_type: str
    component_id: uuid.UUID
    order_index: int = 0
    resolved_version: str = "latest"
    config_override: dict | None = None


@dataclass
class _TransientAgent:
    """Minimal object satisfying generate_agent_config's interface."""

    id: uuid.UUID
    name: str
    description: str
    prompt: str
    model_name: str
    components: list[_TransientComponent] = field(default_factory=list)
    external_mcps: list[dict] = field(default_factory=list)
    required_capabilities: list[str] = field(default_factory=list)


# ── Endpoint ──────────────────────────────────────────────────


@router.post("/preview-config", response_model=PreviewConfigResponse)
async def preview_config(
    req: PreviewConfigRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    optic.debug("preview config")
    target_harnesses = [harness for harness in req.target_harnesses if harness in _VALID_HARNESSES]
    if not target_harnesses:
        target_harnesses = list(HARNESS_REGISTRY)

    components = [
        _TransientComponent(
            component_type=c.component_type,
            component_id=c.component_id,
            order_index=i,
        )
        for i, c in enumerate(req.components)
    ]

    agent = _TransientAgent(
        id=uuid.uuid4(),
        name=req.name or "untitled",
        description=req.description,
        prompt=req.prompt,
        model_name=req.model_name,
        components=components,
    )

    # Resolve component listings by ID (same pattern as install endpoint -
    # the builder UI already scoped what the user can select)
    mcp_ids = [c.component_id for c in components if c.component_type == "mcp"]
    skill_ids = [c.component_id for c in components if c.component_type == "skill"]
    hook_ids = [c.component_id for c in components if c.component_type == "hook"]
    prompt_ids = [c.component_id for c in components if c.component_type == "prompt"]

    mcp_map: dict = {}
    if mcp_ids:
        rows = (await db.execute(select(McpListing).where(McpListing.id.in_(mcp_ids)))).scalars().all()
        mcp_map = {row.id: row for row in rows}

    skill_map: dict = {}
    if skill_ids:
        rows = (await db.execute(select(SkillListing).where(SkillListing.id.in_(skill_ids)))).scalars().all()
        skill_map = {row.id: row for row in rows}

    hook_map: dict = {}
    if hook_ids:
        rows = (
            (
                await db.execute(
                    select(HookListing)
                    .options(selectinload(HookListing.latest_version))
                    .where(HookListing.id.in_(hook_ids))
                )
            )
            .scalars()
            .all()
        )
        hook_map = {row.id: row for row in rows}

    prompt_map: dict = {}
    if prompt_ids:
        rows = (
            (
                await db.execute(
                    select(PromptListing)
                    .options(selectinload(PromptListing.latest_version))
                    .where(PromptListing.id.in_(prompt_ids))
                )
            )
            .scalars()
            .all()
        )
        prompt_map = {row.id: row for row in rows}

    # Build component name map
    name_map: dict[str, str] = {}
    for row in mcp_map.values():
        name_map[str(row.id)] = row.name
    for row in skill_map.values():
        name_map[str(row.id)] = row.name
    for row in hook_map.values():
        name_map[str(row.id)] = row.name
    for row in prompt_map.values():
        name_map[str(row.id)] = row.name

    # Generate configs for all target harnesses
    import json as _json

    configs: dict[str, dict[str, str]] = {}
    placeholder_url = "https://observal.example"

    for harness in target_harnesses:
        try:
            config = generate_agent_config(
                agent=agent,
                harness=harness,
                observal_url=placeholder_url,
                mcp_listings=mcp_map,
                component_names=name_map,
                skill_listings=skill_map,
                hook_listings=hook_map,
                prompt_listings=prompt_map,
            )
        except Exception:
            continue

        files: dict[str, str] = {}
        if "agent_profile" in config:
            rf = config["agent_profile"]
            files[rf["path"]] = rf["content"]
        if "agent_profile" in config:
            af = config["agent_profile"]
            content = af["content"]
            files[af["path"]] = _json.dumps(content, indent=2) if isinstance(content, dict) else content
        if "mcp_config" in config:
            mc = config["mcp_config"]
            if isinstance(mc, dict) and "path" in mc:
                content = mc["content"]
                files[mc["path"]] = _json.dumps(content, indent=2) if isinstance(content, dict) else content
        if "hooks_config" in config:
            hc = config["hooks_config"]
            if isinstance(hc, dict) and "path" in hc:
                content = hc["content"]
                files[hc["path"]] = _json.dumps(content, indent=2) if isinstance(content, dict) else content
        if "skills" in config:
            for sf in config["skills"]:
                files[sf["path"]] = sf["content"]

        if files:
            configs[harness] = files

    return PreviewConfigResponse(configs=configs)
