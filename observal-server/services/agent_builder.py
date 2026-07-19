# SPDX-FileCopyrightText: 2026 Aryan Iyappan <aryaniyappan2006@gmail.com>
# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-FileCopyrightText: 2026 Kaushik Kumar <kaushikrjpm10@gmail.com>
# SPDX-FileCopyrightText: 2026 Lokesh Selvam <lokeshselvam7025@gmail.com>
# SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
# SPDX-FileCopyrightText: 2026 Vishnu Muthiah <vishnu.muthiah04@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""Compose resolved components into portable agent manifests."""

from loguru import logger as optic

from services.agent_builder_types import (
    AgentManifest,
    CompositionSummary,
    ManifestComponent,
    ManifestComponents,
    ManifestError,
)
from services.agent_resolver import ResolvedAgent, ResolvedComponent

# ── Builder Functions ───────────────────────────────────────────────


def _resolved_to_manifest_component(comp: ResolvedComponent) -> ManifestComponent:
    """Convert a ResolvedComponent to a ManifestComponent."""
    kwargs: dict = {
        "name": comp.name,
        "version": comp.version,
        "git_url": comp.git_url,
        "description": comp.description,
        "order": comp.order_index,
    }
    if comp.git_ref:
        kwargs["git_ref"] = comp.git_ref
    if comp.config_override:
        kwargs["config_override"] = comp.config_override

    # Type-specific fields from extra
    if comp.component_type == "mcp":
        if comp.extra.get("transport"):
            kwargs["transport"] = comp.extra["transport"]
        if comp.extra.get("tools_schema"):
            kwargs["tools"] = comp.extra["tools_schema"]
    elif comp.component_type == "skill":
        if comp.extra.get("slash_command"):
            kwargs["slash_command"] = comp.extra["slash_command"]
        if comp.extra.get("task_type"):
            kwargs["task_type"] = comp.extra["task_type"]
        if comp.extra.get("skill_md_content"):
            kwargs["config_override"] = {"skill_md_content": comp.extra["skill_md_content"]}
    elif comp.component_type == "hook":
        kwargs["event"] = comp.extra.get("event", "")
        kwargs["execution_mode"] = comp.extra.get("execution_mode", "async")
        kwargs["priority"] = comp.extra.get("priority", 100)
        kwargs["handler_type"] = comp.extra.get("handler_type", "")
        kwargs["handler_config"] = comp.extra.get("handler_config", {})
    elif comp.component_type == "prompt":
        if comp.extra.get("template"):
            kwargs["template"] = comp.extra["template"]
        if comp.extra.get("variables"):
            kwargs["variables"] = comp.extra["variables"]
    elif comp.component_type == "sandbox":
        kwargs["image"] = comp.extra.get("image", "")
        kwargs["runtime_type"] = comp.extra.get("runtime_type", "")
        if comp.extra.get("resource_limits"):
            kwargs["resource_limits"] = comp.extra["resource_limits"]
        if comp.extra.get("network_policy"):
            kwargs["network_policy"] = comp.extra["network_policy"]
        if comp.extra.get("entrypoint"):
            kwargs["entrypoint"] = comp.extra["entrypoint"]
        if comp.extra.get("runtime_config"):
            kwargs["runtime_config"] = comp.extra["runtime_config"]

    return ManifestComponent(**kwargs)


def build_agent_manifest(resolved: ResolvedAgent) -> dict:
    """Build a portable agent manifest from a fully resolved agent.

    Returns a clean dict with only populated fields.
    """
    optic.trace("building agent config for {}", resolved.agent_name)
    type_map = {
        "mcp": "mcps",
        "skill": "skills",
        "hook": "hooks",
        "prompt": "prompts",
        "sandbox": "sandboxes",
    }

    grouped: dict[str, list[ManifestComponent]] = {}
    for ctype, key in type_map.items():
        typed = resolved.components_by_type(ctype)
        if typed:
            grouped[key] = [_resolved_to_manifest_component(c) for c in typed]

    manifest = AgentManifest(
        name=resolved.agent_name,
        version=resolved.agent_version,
        prompt=resolved.agent_prompt,
        description=resolved.agent_description,
        model_name=resolved.model_name,
        models_by_harness=resolved.models_by_harness,
        components=ManifestComponents(**grouped),
        errors=[
            ManifestError(
                component_type=e.component_type,
                component_id=str(e.component_id),
                reason=e.reason,
            )
            for e in resolved.errors
        ],
    )
    return manifest.model_dump_compact()


def build_composition_summary(resolved: ResolvedAgent) -> dict:
    """Build a lightweight summary of the agent's composition for API responses."""
    optic.trace("building agent config for {}", resolved.agent_name)
    type_map = {
        "mcp": "mcps",
        "skill": "skills",
        "hook": "hooks",
        "prompt": "prompts",
        "sandbox": "sandboxes",
    }

    component_counts: dict[str, int] = {}
    components_by_key: dict[str, list[dict]] = {}

    for ctype, key in type_map.items():
        typed = resolved.components_by_type(ctype)
        if typed:
            component_counts[ctype] = len(typed)
            components_by_key[key] = [{"name": c.name, "version": c.version, "order": c.order_index} for c in typed]

    summary = CompositionSummary(
        agent_id=str(resolved.agent_id),
        agent_name=resolved.agent_name,
        agent_version=resolved.agent_version,
        resolved=resolved.ok,
        component_counts=component_counts,
        components=components_by_key,
        errors=[
            ManifestError(
                component_type=e.component_type,
                component_id=str(e.component_id),
                reason=e.reason,
            )
            for e in resolved.errors
        ],
    )
    return summary.model_dump(exclude_none=True)
