# SPDX-FileCopyrightText: 2026 Aryan Iyappan <aryaniyappan2006@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""Build a deterministic YAML snapshot of an :class:`AgentVersion`.

The snapshot is the canonical text the reviewer reads when approving a
new version, and the source for the version-diff endpoint when neither
side carries a client-supplied snapshot. Centralising the shape here
guarantees the web builder, the CLI publish flow and the diff fallback
all surface the same fields - including per-harness model overrides
(``models_by_harness``) which are otherwise easy to omit.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import yaml
from sqlalchemy import select

from models.agent_component import AgentComponent
from models.hook import HookListing
from models.mcp import McpListing
from models.prompt import PromptListing
from models.sandbox import SandboxListing
from models.skill import SkillListing

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from models.agent import AgentVersion
from loguru import logger as optic

_LISTING_MODELS = {
    "mcp": McpListing,
    "skill": SkillListing,
    "hook": HookListing,
    "prompt": PromptListing,
    "sandbox": SandboxListing,
}


def _normalise_models_by_harness(value: object) -> dict[str, str]:
    """Coerce ``models_by_harness`` into a plain dict for YAML serialisation."""
    optic.trace("normalising models_by_harness value: {}", type(value).__name__)
    if not isinstance(value, dict):
        return {}
    return {str(k): str(v) for k, v in value.items() if v}


async def _resolve_component_details(ver: AgentVersion, db: AsyncSession) -> list[dict]:
    """Return human-friendly component entries for the snapshot.

    Re-queries ``agent_components`` from the database rather than reading
    ``ver.components`` directly. The relationship attribute may be stale
    when a freshly created version's components were added in the same
    session but the back-reference wasn't synchronously synced.
    """
    optic.trace("resolving component details for version {}", getattr(ver, "version", "?"))
    rows = (
        (
            await db.execute(
                select(AgentComponent)
                .where(AgentComponent.agent_version_id == ver.id)
                .order_by(AgentComponent.order_index)
            )
        )
        .scalars()
        .all()
    )
    if not rows:
        return []
    details: list[dict] = []
    for comp in rows:
        entry: dict = {
            "type": comp.component_type,
            "id": str(comp.component_id),
        }
        model = _LISTING_MODELS.get(comp.component_type)
        listing = None
        if model is not None:
            listing = (await db.execute(select(model).where(model.id == comp.component_id))).scalar_one_or_none()
        if listing is not None:
            entry["name"] = getattr(listing, "name", "") or comp.component_name or ""
            if comp.component_type == "prompt":
                entry["template"] = getattr(listing, "template", "") or ""
            else:
                entry["description"] = getattr(listing, "description", "") or ""
        else:
            entry["name"] = comp.component_name or str(comp.component_id)[:8]
        if comp.resolved_version:
            entry["version"] = comp.resolved_version
        if comp.config_override:
            entry["config_override"] = comp.config_override
        details.append(entry)
    return details


async def build_yaml_snapshot(ver: AgentVersion, db: AsyncSession) -> str:
    """Render *ver* as a YAML document suitable for ``ver.yaml_snapshot``.

    The returned string is deterministic: keys are emitted in a fixed order
    and ``models_by_harness`` is always present (empty dict when the author
    didn't override anything) so a reviewer can trust an empty section
    means "no per-harness overrides", not "missing data".
    """
    optic.trace("resolving component details for version {}", getattr(ver, "version", "?"))
    components = await _resolve_component_details(ver, db)
    data: dict = {
        "version": ver.version,
        "description": ver.description or "",
        "model_name": ver.model_name or "",
        "models_by_harness": _normalise_models_by_harness(ver.models_by_harness),
        "supported_harnesses": list(ver.supported_harnesses or []),
        "external_mcps": list(ver.external_mcps or []),
        "components": components,
        "prompt": ver.prompt or "",
    }
    if ver.model_config_json:
        data["model_config_json"] = ver.model_config_json
    if ver.success_criteria:
        data["success_criteria"] = ver.success_criteria
    header = "# Auto-generated snapshot - review the structured fields above and the prompt below.\n"
    return header + yaml.safe_dump(data, sort_keys=False, default_flow_style=False, allow_unicode=True)


async def build_lock_snapshot(
    ver: AgentVersion,
    db: AsyncSession,
    agent_name: str | None = None,
) -> str:
    """Render *ver* as an observal-agent.lock YAML document for ``ver.lock_snapshot``.

    Computes integrity hashes for prompt template contents and captures exact
    pinned component versions.
    """
    from models.agent import Agent
    from models.prompt import PromptVersion
    from services.agent_lock_file import generate_lock_file

    optic.trace("building lock snapshot for version {}", getattr(ver, "version", "?"))
    rows = []
    ver_id = getattr(ver, "id", None)
    if isinstance(ver_id, uuid.UUID):
        try:
            exec_res = await db.execute(
                select(AgentComponent)
                .where(AgentComponent.agent_version_id == ver_id)
                .order_by(AgentComponent.order_index)
            )
            if hasattr(exec_res, "scalars"):
                rows = exec_res.scalars().all()
        except Exception:
            rows = []

    if not rows and getattr(ver, "components", None):
        rows = list(ver.components)

    resolved_components: list[dict] = []
    for comp in rows:
        cid = getattr(comp, "component_id", None)
        if not isinstance(cid, (str, uuid.UUID)):
            continue
        raw_ctype = getattr(comp, "component_type", None)
        ctype = raw_ctype if isinstance(raw_ctype, str) else ""
        raw_cname = getattr(comp, "component_name", None)
        cname = raw_cname if isinstance(raw_cname, str) else ""
        raw_resolved = getattr(comp, "resolved_version", None)
        resolved = raw_resolved if isinstance(raw_resolved, str) and raw_resolved else "latest"
        model = _LISTING_MODELS.get(ctype)
        listing = None
        if model is not None and cid is not None:
            try:
                l_res = await db.execute(select(model).where(model.id == cid))
                if hasattr(l_res, "scalar_one_or_none"):
                    listing = l_res.scalar_one_or_none()
            except Exception:
                listing = None

        if listing is not None:
            listing_name = getattr(listing, "name", None)
            cname = cname or (listing_name if isinstance(listing_name, str) else "") or str(cid)[:8]
            if resolved == "latest":
                listing_ver = getattr(listing, "version", None)
                resolved = (listing_ver if isinstance(listing_ver, str) else None) or "latest"
        else:
            cname = cname or str(cid)[:8]

        content = None
        source_sha = None
        if ctype == "prompt":
            if resolved != "latest" and listing and getattr(listing, "version", None) != resolved:
                try:
                    p_res = await db.execute(
                        select(PromptVersion).where(
                            PromptVersion.listing_id == cid,
                            PromptVersion.version == resolved,
                        )
                    )
                    pver = p_res.scalar_one_or_none() if hasattr(p_res, "scalar_one_or_none") else None
                    if pver and getattr(pver, "template", None):
                        raw_tpl = getattr(pver, "template", None)
                        if isinstance(raw_tpl, str):
                            content = raw_tpl
                except Exception:
                    pass
            if content is None and listing is not None:
                raw_tpl = getattr(listing, "template", None)
                if isinstance(raw_tpl, str):
                    content = raw_tpl
        elif ctype == "hook":
            raw_sha = getattr(listing, "resolved_sha", None)
            if isinstance(raw_sha, str):
                source_sha = raw_sha

        entry = {
            "type": ctype,
            "name": cname,
            "resolved": resolved,
            "id": str(cid),
        }
        if source_sha:
            entry["source_sha"] = source_sha
        if content:
            entry["content"] = content
        resolved_components.append(entry)

    ver_agent_id = getattr(ver, "agent_id", None)
    if not agent_name and isinstance(ver_agent_id, uuid.UUID):
        try:
            a_res = await db.execute(select(Agent.name).where(Agent.id == ver_agent_id))
            agent_row = a_res.scalar_one_or_none() if hasattr(a_res, "scalar_one_or_none") else None
            if isinstance(agent_row, str):
                agent_name = agent_row
        except Exception:
            pass

    try:
        ver_str = getattr(ver, "version", None)
        return generate_lock_file(
            resolved_components,
            agent=agent_name if isinstance(agent_name, str) else None,
            agent_version=ver_str if isinstance(ver_str, str) else None,
        )
    except Exception as exc:
        optic.warning("failed to generate lock snapshot: {}", exc)
        return ""
