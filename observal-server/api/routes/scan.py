"""Bulk scan endpoint: register multiple component types in one call.

DEPRECATED: The CLI no longer calls this endpoint as of the scan redesign.
Kept for backwards compatibility with older CLI versions. Use
'observal registry <type> submit' for explicit component publishing.
"""

import warnings

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import get_db, require_role
from models.agent import Agent, AgentGoalSection, AgentGoalTemplate
from models.hook import HookListing
from models.mcp import ListingStatus, McpListing
from models.skill import SkillListing
from models.user import User, UserRole

router = APIRouter(prefix="/api/v1/scan", tags=["scan"])


# ── Request models ──────────────────────────────────────────


class ScannedMcp(BaseModel):
    name: str
    command: str | None = None
    args: list[str] = []
    url: str | None = None
    env: dict[str, str] = {}
    description: str = ""
    source_plugin: str | None = None
    source_ide: str = ""


class ScannedSkill(BaseModel):
    name: str
    description: str = ""
    source_plugin: str | None = None
    task_type: str = "general"
    skill_path: str = "/"
    source_ide: str = ""


class ScannedHook(BaseModel):
    name: str
    event: str
    handler_type: str = "command"
    handler_config: dict = {}
    description: str = ""
    source_plugin: str | None = None
    source_ide: str = ""


class ScannedAgent(BaseModel):
    name: str
    description: str = ""
    model_name: str = ""
    prompt: str = ""
    source_file: str | None = None
    source_ide: str = ""


class ScanRequest(BaseModel):
    ide: str
    mcps: list[ScannedMcp] = []
    skills: list[ScannedSkill] = []
    hooks: list[ScannedHook] = []
    agents: list[ScannedAgent] = []


# ── Response models ─────────────────────────────────────────


class RegisteredItem(BaseModel):
    name: str
    id: str
    type: str  # "mcp", "skill", "hook", "agent"
    status: str  # "created" or "existing"


class ScanResponse(BaseModel):
    registered: list[RegisteredItem] = []
    summary: dict[str, int] = {}


# ── Endpoint ────────────────────────────────────────────────


@router.post("", response_model=ScanResponse, deprecated=True)
async def bulk_scan(
    req: ScanRequest,
    response: Response,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.user)),
):
    response.headers["X-Deprecated"] = "Use 'observal registry <type> submit' instead"
    warnings.warn("POST /api/v1/scan is deprecated; use explicit submit endpoints", DeprecationWarning, stacklevel=1)
    registered = []
    counts: dict[str, int] = {"mcp": 0, "skill": 0, "hook": 0, "agent": 0}

    owner = current_user.username or current_user.name or str(current_user.id)

    # ── MCPs ────────────────────────────────────────────
    for mcp in req.mcps:
        result = await db.execute(select(McpListing).where(McpListing.name == mcp.name))
        existing = result.scalar_one_or_none()
        if existing:
            registered.append(RegisteredItem(name=mcp.name, id=str(existing.id), type="mcp", status="existing"))
            counts["mcp"] += 1
            continue

        ide_tag = mcp.source_ide or req.ide
        listing = McpListing(
            name=mcp.name,
            version="0.1.0",
            git_url=mcp.url or "",
            description=mcp.description or f"Auto-scanned MCP from {ide_tag}: {mcp.name}",
            category="scanned",
            owner=owner,
            supported_ides=[ide_tag],
            status=ListingStatus.pending,
            submitted_by=current_user.id,
        )
        db.add(listing)
        await db.flush()
        registered.append(RegisteredItem(name=mcp.name, id=str(listing.id), type="mcp", status="created"))
        counts["mcp"] += 1

    # ── Skills ──────────────────────────────────────────
    for skill in req.skills:
        result = await db.execute(select(SkillListing).where(SkillListing.name == skill.name))
        existing = result.scalar_one_or_none()
        if existing:
            registered.append(RegisteredItem(name=skill.name, id=str(existing.id), type="skill", status="existing"))
            counts["skill"] += 1
            continue

        ide_tag = skill.source_ide or req.ide
        listing = SkillListing(
            name=skill.name,
            version="0.1.0",
            description=skill.description or f"Auto-scanned skill: {skill.name}",
            owner=owner,
            task_type=skill.task_type,
            skill_path=skill.skill_path,
            supported_ides=[ide_tag],
            status=ListingStatus.pending,
            submitted_by=current_user.id,
        )
        db.add(listing)
        await db.flush()
        registered.append(RegisteredItem(name=skill.name, id=str(listing.id), type="skill", status="created"))
        counts["skill"] += 1

    # ── Hooks ───────────────────────────────────────────
    for hook in req.hooks:
        result = await db.execute(select(HookListing).where(HookListing.name == hook.name))
        existing = result.scalar_one_or_none()
        if existing:
            registered.append(RegisteredItem(name=hook.name, id=str(existing.id), type="hook", status="existing"))
            counts["hook"] += 1
            continue

        ide_tag = hook.source_ide or req.ide
        listing = HookListing(
            name=hook.name,
            version="0.1.0",
            description=hook.description or f"Auto-scanned hook: {hook.name}",
            owner=owner,
            event=hook.event,
            handler_type=hook.handler_type,
            handler_config=hook.handler_config,
            supported_ides=[ide_tag],
            status=ListingStatus.pending,
            submitted_by=current_user.id,
        )
        db.add(listing)
        await db.flush()
        registered.append(RegisteredItem(name=hook.name, id=str(listing.id), type="hook", status="created"))
        counts["hook"] += 1

    # ── Agents ──────────────────────────────────────────
    for agent in req.agents:
        result = await db.execute(select(Agent).where(Agent.name == agent.name))
        existing = result.scalar_one_or_none()
        if existing:
            registered.append(RegisteredItem(name=agent.name, id=str(existing.id), type="agent", status="existing"))
            counts["agent"] += 1
            continue

        ide_tag = agent.source_ide or req.ide
        new_agent = Agent(
            name=agent.name,
            version="0.1.0",
            description=agent.description or f"Auto-scanned agent: {agent.name}",
            owner=owner,
            prompt=agent.prompt or "",
            model_name=agent.model_name or "sonnet-4-6",
            supported_ides=[ide_tag],
            created_by=current_user.id,
        )
        db.add(new_agent)
        await db.flush()

        goal_template = AgentGoalTemplate(
            agent_id=new_agent.id,
            description=agent.description or f"Goal for {agent.name}",
        )
        db.add(goal_template)
        await db.flush()

        section = AgentGoalSection(
            goal_template_id=goal_template.id,
            name="default",
            description="Default goal section",
            order=0,
        )
        db.add(section)
        await db.flush()

        registered.append(RegisteredItem(name=agent.name, id=str(new_agent.id), type="agent", status="created"))
        counts["agent"] += 1

    await db.commit()
    return ScanResponse(registered=registered, summary=counts)
