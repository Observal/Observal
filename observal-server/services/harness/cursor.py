# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""Cursor harness adapter for agent config generation."""

from __future__ import annotations

from loguru import logger as optic

from observal_shared.harness_registry import HARNESS_REGISTRY
from services.harness import BaseHarnessAdapter, ConfigContext, register_adapter
from services.harness.helpers import (
    _collect_hook_script_files,
    _cursor_hooks_config,
    _merge_hook_components_into_config,
)


class CursorAdapter(BaseHarnessAdapter):
    """Cursor harness adapter."""

    @property
    def harness_name(self) -> str:
        return "cursor"

    def format_hook_install_snippet(self, event: str, handler_type: str, command: str, timeout: int | None) -> dict:
        return {"version": 1, "hooks": {event: [{"command": command}]}}

    def format_hook_telemetry(self, hook_listing, server_url: str, platform: str) -> dict:
        entry = {"type": "http", "url": f"{server_url}/api/v1/telemetry/hooks", "timeout": 10}
        return {"hooks": {str(hook_listing.event): [{"matcher": "*", "hooks": [entry]}]}}

    def format_config(self, ctx: ConfigContext) -> dict:
        optic.trace("ctx={}", ctx)
        safe_name = ctx.safe_name
        options = ctx.options
        mcp_configs = ctx.mcp_configs
        rules_content = ctx.rules_content
        hook_configs = ctx.hook_configs
        skill_configs = ctx.skill_configs
        platform = ctx.platform

        spec = HARNESS_REGISTRY["cursor"]
        ide_scope = options.get("scope", spec.get("default_scope", "project"))
        mcp_paths = spec.get("mcp_config", {})
        mcp_path = mcp_paths.get(ide_scope, next(iter(mcp_paths.values()), ".mcp.json"))

        desc_line = (ctx.agent.description or safe_name).replace("\n", " ").strip()[:200]
        model = options.get("_resolved_model") or "inherit"
        cursor_agent_content = (
            f"---\nname: {safe_name}\ndescription: {desc_line!r}\nmodel: {model}\n---\n\n{rules_content}"
        )

        result: dict = {
            "mcp_config": {"path": mcp_path, "content": {spec.get("mcp_servers_key", "mcpServers"): mcp_configs}},
            "scope": ide_scope,
        }

        agent_dir = ".cursor/agents" if ide_scope == "project" else "~/.cursor/agents"
        result["agent_profile"] = {"path": f"{agent_dir}/{safe_name}.md", "content": cursor_agent_content}

        # Hooks config
        hooks_path = ".cursor/hooks.json" if ide_scope == "project" else "~/.cursor/hooks.json"
        hooks_content = _cursor_hooks_config(platform=platform)
        _merge_hook_components_into_config(hooks_content, hook_configs, "cursor")
        result["hooks_config"] = {
            "path": hooks_path,
            "content": hooks_content,
            "merge": True,
        }

        # Hook script files
        hook_files = _collect_hook_script_files(hook_configs, ctx.hook_listings, "cursor")
        if hook_files:
            result["hook_files"] = hook_files
        if skill_configs:
            result["skill_components"] = skill_configs
        if ctx.compatibility_warnings:
            result["_warnings"] = ctx.compatibility_warnings

        return result


register_adapter(CursorAdapter())
