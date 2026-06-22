# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Harness adapter protocol, context, and registry."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass
class ConfigContext:
    """Shared pre-computed data passed to each harness adapter."""

    agent: Any  # Agent model instance
    safe_name: str
    harness: str
    observal_url: str
    mcp_configs: dict = field(default_factory=dict)
    rules_content: str = ""
    skill_configs: list = field(default_factory=list)
    hook_configs: list = field(default_factory=list)
    options: dict = field(default_factory=dict)
    platform: str = ""
    compatibility_warnings: list = field(default_factory=list)
    # Optional component listings (passed through for adapters that need them)
    mcp_listings: dict | None = None
    hook_listings: dict | None = None
    skill_listings: dict | None = None
    sandbox_listings: dict | None = None


@runtime_checkable
class HarnessAdapter(Protocol):
    """Protocol defining the interface for harness-specific config generation."""

    @property
    def harness_name(self) -> str:
        """Canonical harness name (e.g. 'claude-code', 'cursor')."""
        ...

    def format_config(self, ctx: ConfigContext) -> dict:
        """Format the pre-computed context into harness-specific config output."""
        ...


# ── Adapter Registry ──────────────────────────────────────────────

_ADAPTER_REGISTRY: dict[str, HarnessAdapter] = {}


def register_adapter(adapter: HarnessAdapter) -> None:
    """Register a harness adapter instance."""
    _ADAPTER_REGISTRY[adapter.harness_name] = adapter


def get_adapter(harness: str) -> HarnessAdapter | None:
    """Look up an adapter by harness name. Returns None if not registered."""
    return _ADAPTER_REGISTRY.get(harness)


def get_all_adapters() -> dict[str, HarnessAdapter]:
    """Return all registered adapters."""
    return dict(_ADAPTER_REGISTRY)


# ── Orchestrator ──────────────────────────────────────────────────


def generate_agent_config(
    agent: Any,
    harness: str,
    observal_url: str = "http://localhost:8000",
    mcp_listings: dict | None = None,
    component_names: dict | None = None,
    env_values: dict | None = None,
    header_values: dict | None = None,
    options: dict | None = None,
    platform: str = "",
    skill_listings: dict | None = None,
    hook_listings: dict | None = None,
    prompt_listings: dict | None = None,
    sandbox_listings: dict | None = None,
) -> dict:
    """Generate harness-specific config for an agent.

    This is the single entry point for all harness config generation.
    It builds a shared ConfigContext, resolves the adapter, and delegates.
    """
    import services.harness.load_all  # noqa: F401
    from services.harness.helpers import (
        _build_hook_configs,
        _build_mcp_configs,
        _build_rules_content,
        _build_sandbox_mcp_entry,
        _build_skill_configs,
        _check_harness_compatibility,
        _sanitize_name,
    )

    safe_name = _sanitize_name(agent.name)
    mcp_configs = _build_mcp_configs(
        agent, harness, observal_url, mcp_listings=mcp_listings, env_values=env_values, header_values=header_values
    )

    if sandbox_listings:
        sandbox_mcp = _build_sandbox_mcp_entry(sandbox_listings, harness)
        if sandbox_mcp:
            mcp_configs.update(sandbox_mcp)

    rules_content = _build_rules_content(agent, component_names, prompt_listings, sandbox_listings)
    skill_configs = _build_skill_configs(agent, skill_listings)
    hook_configs = _build_hook_configs(agent, hook_listings)
    options = options or {}
    compatibility_warnings = _check_harness_compatibility(agent, harness)

    adapter = get_adapter(harness)
    if adapter is None:
        raise ValueError(f"No adapter registered for harness: {harness!r}")

    ctx = ConfigContext(
        agent=agent,
        safe_name=safe_name,
        harness=harness,
        observal_url=observal_url,
        mcp_configs=mcp_configs,
        rules_content=rules_content,
        skill_configs=skill_configs,
        hook_configs=hook_configs,
        options=options,
        platform=platform,
        compatibility_warnings=compatibility_warnings,
        mcp_listings=mcp_listings,
        hook_listings=hook_listings,
        skill_listings=skill_listings,
        sandbox_listings=sandbox_listings,
    )
    return adapter.format_config(ctx)


async def generate_all_harness_configs(
    agent_version: Any,
    agent: Any,
    target_harnesses: list[str] | None = None,
    observal_url: str = "http://localhost:8000",
    mcp_listings: dict | None = None,
    skill_listings: dict | None = None,
    hook_listings: dict | None = None,
    component_names: dict | None = None,
    env_values: dict | None = None,
) -> dict[str, dict[str, str]]:
    """Generate harness config files for all target harnesses from an AgentVersion."""
    import json as _json

    from schemas.harness_registry import HARNESS_REGISTRY

    harnesses = target_harnesses or agent_version.supported_harnesses or list(HARNESS_REGISTRY.keys())
    result = {}

    for harness in harnesses:
        if harness not in HARNESS_REGISTRY:
            continue
        config = generate_agent_config(
            agent=agent,
            harness=harness,
            observal_url=observal_url,
            mcp_listings=mcp_listings,
            skill_listings=skill_listings,
            hook_listings=hook_listings,
            component_names=component_names,
            env_values=env_values,
        )

        files = {}
        if "agent_profile" in config:
            af = config["agent_profile"]
            content = af["content"]
            files[af["path"]] = _json.dumps(content, indent=2) if isinstance(content, dict) else content
        if "mcp_config" in config:
            mc = config["mcp_config"]
            if isinstance(mc, dict) and "path" in mc:
                content = mc["content"]
                files[mc["path"]] = _json.dumps(content, indent=2) if isinstance(content, dict) else content
        if "skills" in config:
            for sf in config["skills"]:
                files[sf["path"]] = sf["content"]

        if files:
            result[harness] = {"files": files}

    return result
