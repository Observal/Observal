"""Agent builder — composes resolved components into a portable agent manifest."""

import logging

from services.agent_resolver import ResolvedAgent, ResolvedComponent

logger = logging.getLogger(__name__)


def build_agent_manifest(resolved: ResolvedAgent) -> dict:
    """Build a portable agent manifest from a fully resolved agent.

    Returns a dict that represents the agent.yaml structure:
    {
      "name": "code-reviewer",
      "version": "1.0.0",
      "components": {
        "mcps": [...],
        "skills": [...],
        "hooks": [...],
        "prompts": [...],
        "sandboxes": [...],
      },
      "errors": [...]  # only if resolution had errors
    }
    """
    manifest: dict = {
        "name": resolved.agent_name,
        "version": resolved.agent_version,
        "components": {},
    }

    type_keys = {
        "mcp": "mcps",
        "skill": "skills",
        "hook": "hooks",
        "prompt": "prompts",
        "sandbox": "sandboxes",
    }

    for ctype, key in type_keys.items():
        typed_comps = resolved.components_by_type(ctype)
        if typed_comps:
            manifest["components"][key] = [
                _component_to_manifest_entry(c) for c in typed_comps
            ]

    if resolved.errors:
        manifest["errors"] = [
            {
                "component_type": e.component_type,
                "component_id": str(e.component_id),
                "reason": e.reason,
            }
            for e in resolved.errors
        ]

    return manifest


def _component_to_manifest_entry(comp: ResolvedComponent) -> dict:
    """Convert a resolved component to its manifest representation."""
    entry: dict = {
        "name": comp.name,
        "version": comp.version,
        "git_url": comp.git_url,
        "description": comp.description,
        "order": comp.order_index,
    }
    if comp.git_ref:
        entry["git_ref"] = comp.git_ref
    if comp.config_override:
        entry["config_override"] = comp.config_override

    # Carry through type-specific fields that matter for installation
    if comp.component_type == "mcp":
        if comp.extra.get("transport"):
            entry["transport"] = comp.extra["transport"]
        if comp.extra.get("tools_schema"):
            entry["tools"] = comp.extra["tools_schema"]
    elif comp.component_type == "skill":
        if comp.extra.get("slash_command"):
            entry["slash_command"] = comp.extra["slash_command"]
        if comp.extra.get("task_type"):
            entry["task_type"] = comp.extra["task_type"]
    elif comp.component_type == "hook":
        entry["event"] = comp.extra.get("event", "")
        entry["execution_mode"] = comp.extra.get("execution_mode", "async")
        entry["priority"] = comp.extra.get("priority", 100)
    elif comp.component_type == "prompt":
        if comp.extra.get("template"):
            entry["template"] = comp.extra["template"]
        if comp.extra.get("variables"):
            entry["variables"] = comp.extra["variables"]
    elif comp.component_type == "sandbox":
        entry["image"] = comp.extra.get("image", "")
        entry["runtime_type"] = comp.extra.get("runtime_type", "")
        if comp.extra.get("resource_limits"):
            entry["resource_limits"] = comp.extra["resource_limits"]

    return entry


def build_composition_summary(resolved: ResolvedAgent) -> dict:
    """Build a lightweight summary of the agent's composition for API responses."""
    type_keys = {
        "mcp": "mcps",
        "skill": "skills",
        "hook": "hooks",
        "prompt": "prompts",
        "sandbox": "sandboxes",
    }

    summary: dict = {
        "agent_id": str(resolved.agent_id),
        "agent_name": resolved.agent_name,
        "agent_version": resolved.agent_version,
        "resolved": resolved.ok,
        "component_counts": {},
        "components": {},
    }

    for ctype, key in type_keys.items():
        typed = resolved.components_by_type(ctype)
        if typed:
            summary["component_counts"][ctype] = len(typed)
            summary["components"][key] = [
                {
                    "name": c.name,
                    "version": c.version,
                    "order": c.order_index,
                }
                for c in typed
            ]

    if resolved.errors:
        summary["errors"] = [
            {
                "component_type": e.component_type,
                "component_id": str(e.component_id),
                "reason": e.reason,
            }
            for e in resolved.errors
        ]

    return summary
