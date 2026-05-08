"""Preview endpoint — generates full IDE config without persisting an agent."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from api.deps import get_current_user, get_db
from api.ratelimit import limiter
from models.hook import HookListing
from models.mcp import McpListing
from models.prompt import PromptListing
from models.skill import SkillListing
from models.user import User
from schemas.ide_registry import IDE_REGISTRY
from services.agent_config_generator import generate_agent_config

router = APIRouter(prefix="/api/v1/agents", tags=["agents"])

_VALID_IDES = set(IDE_REGISTRY.keys())
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
    target_ides: list[str] = Field(default_factory=list, max_length=9)


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
    required_ide_features: list[str] = field(default_factory=list)


# ── Endpoint ──────────────────────────────────────────────────


@router.post("/preview-config", response_model=PreviewConfigResponse)
@limiter.limit("10/minute")
async def preview_config(
    req: PreviewConfigRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    target_ides = [ide for ide in req.target_ides if ide in _VALID_IDES]
    if not target_ides:
        target_ides = [ide for ide in IDE_REGISTRY if ide != "copilot-cli"]

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

    # Resolve component listings by ID (same pattern as install endpoint —
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
            await db.execute(
                select(HookListing)
                .options(selectinload(HookListing.latest_version))
                .where(HookListing.id.in_(hook_ids))
            )
        ).scalars().all()
        hook_map = {row.id: row for row in rows}

    prompt_map: dict = {}
    if prompt_ids:
        rows = (
            await db.execute(
                select(PromptListing)
                .options(selectinload(PromptListing.latest_version))
                .where(PromptListing.id.in_(prompt_ids))
            )
        ).scalars().all()
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

    # Generate configs for all target IDEs
    import json as _json

    configs: dict[str, dict[str, str]] = {}
    placeholder_url = "https://observal.example"

    for ide in target_ides:
        try:
            config = generate_agent_config(
                agent=agent,
                ide=ide,
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
        if "rules_file" in config:
            rf = config["rules_file"]
            files[rf["path"]] = rf["content"]
        if "agent_file" in config:
            af = config["agent_file"]
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
        if "skill_files" in config:
            for sf in config["skill_files"]:
                files[sf["path"]] = sf["content"]

        if files:
            configs[ide] = files

    return PreviewConfigResponse(configs=configs)
