# SPDX-FileCopyrightText: 2026 Lokesh Selvam <lokeshselvam7025@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""OpenCode harness adapter for agent config generation.

Generates full config when a user installs an agent for OpenCode, including:
- Rules file (agent markdown at .opencode/agents/ or ~/.config/opencode/agents/)
- MCP config (opencode.json with "mcp" key)
- Agent profile and MCP config
- Custom hook plugins (one .ts file per hook component)
- Skills (SKILL.md files in .opencode/skills/ or ~/.config/opencode/skills/)
"""

from __future__ import annotations

from loguru import logger as optic

from schemas.harness_registry import HARNESS_REGISTRY
from services.harness import ConfigContext, register_adapter
from services.harness.helpers import (
    _collect_hook_script_files,
    _collect_opencode_hook_plugins,
)


class OpenCodeAdapter:
    """OpenCode harness adapter."""

    @property
    def harness_name(self) -> str:
        return "opencode"

    def format_config(self, ctx: ConfigContext) -> dict:
        optic.trace("ctx={}", ctx)
        safe_name = ctx.safe_name
        options = ctx.options
        mcp_configs = ctx.mcp_configs
        rules_content = ctx.rules_content
        skill_configs = ctx.skill_configs
        hook_configs = ctx.hook_configs

        opencode_spec = HARNESS_REGISTRY["opencode"]
        opencode_scope = options.get("scope", opencode_spec["default_scope"])

        # Build MCP configs in OpenCode's format:
        # { "mcp": { "name": { "type": "local", "command": [...] } } }
        opencode_mcp = {}
        for k, v in mcp_configs.items():
            if v.get("type") in ("local", "remote"):
                # Already in OpenCode format (from generate_config for opencode harness)
                # Normalize env key: generate_config uses "env", OpenCode expects "environment"
                entry = dict(v)
                if "env" in entry and "environment" not in entry:
                    entry["environment"] = entry.pop("env")
                opencode_mcp[k] = entry
            else:
                # Standard format from _build_mcp_configs: {command, args, env}
                cmd_array = [v["command"], *v.get("args", [])]
                entry = {"type": "local", "command": cmd_array}
                if v.get("env"):
                    entry["environment"] = v["env"]
                opencode_mcp[k] = entry

        rules_path = opencode_spec["agent_profile"][opencode_scope].format(name=safe_name)
        mcp_path = opencode_spec["mcp_config"].get(opencode_scope, next(iter(opencode_spec["mcp_config"].values())))
        opencode_content: dict = {opencode_spec["mcp_servers_key"]: opencode_mcp}
        opencode_model = options.get("_resolved_model")
        if opencode_model:
            opencode_content["model"] = opencode_model

        result: dict = {
            "agent_profile": {"path": rules_path, "content": rules_content},
            "mcp_config": {"path": mcp_path, "content": opencode_content},
            "scope": opencode_scope,
        }

        # Pass skill configs through for CLI-side installation
        if skill_configs:
            result["skill_components"] = skill_configs

        # Generate custom hook plugins + script files
        if hook_configs:
            hook_plugins = _collect_opencode_hook_plugins(hook_configs)
            hook_scripts = _collect_hook_script_files(hook_configs, None, "opencode")
            if hook_plugins or hook_scripts:
                result["hook_files"] = hook_plugins + hook_scripts

        warnings_combined = list(ctx.compatibility_warnings)
        warnings_combined.extend(options.get("_model_warnings") or [])
        if warnings_combined:
            result["_warnings"] = warnings_combined

        return result


register_adapter(OpenCodeAdapter())
