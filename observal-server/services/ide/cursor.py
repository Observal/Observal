# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Cursor IDE adapter for agent config generation."""

from __future__ import annotations

from loguru import logger

from schemas.ide_registry import IDE_REGISTRY
from services.ide import ConfigContext, register_adapter
from services.ide.helpers import (
    _collect_hook_script_files,
    _cursor_hooks_config,
    _generate_skill_file,
    _merge_hook_components_into_config,
)


class CursorAdapter:
    """Cursor IDE adapter."""

    @property
    def ide_name(self) -> str:
        logger.debug("ide_name called")
        return "cursor"

    def format_config(self, ctx: ConfigContext) -> dict:
        logger.debug("format_config: ctx={}", ctx)
        safe_name = ctx.safe_name
        options = ctx.options
        mcp_configs = ctx.mcp_configs
        rules_content = ctx.rules_content
        hook_configs = ctx.hook_configs
        skill_configs = ctx.skill_configs
        platform = ctx.platform

        spec = IDE_REGISTRY["cursor"]
        ide_scope = options.get("scope", spec.get("default_scope", "project"))
        rules_paths = spec.get("rules_file", {})
        rules_path = rules_paths.get(ide_scope, next(iter(rules_paths.values()), f".rules/{safe_name}.md"))
        mcp_paths = spec.get("mcp_config_path", {})
        mcp_path = mcp_paths.get(ide_scope, next(iter(mcp_paths.values()), ".mcp.json"))

        skill_files = [_generate_skill_file(s, "cursor", ide_scope) for s in skill_configs]
        skill_files = [f for f in skill_files if f]

        # Cursor uses .cursor/agents/<name>.md for subagent registration
        # and .cursor/rules/<name>.mdc for context rules
        desc_line = (ctx.agent.description or safe_name).replace("\n", " ").strip()[:200]
        cursor_rules_content = f"---\ndescription: {desc_line}\nalwaysApply: false\n---\n\n{rules_content}"
        cursor_agent_content = f"---\nname: {safe_name}\ndescription: {desc_line}\n---\n\n{rules_content}"

        result: dict = {
            "rules_file": {"path": rules_path.format(name=safe_name), "content": cursor_rules_content},
            "mcp_config": {"path": mcp_path, "content": {spec.get("mcp_servers_key", "mcpServers"): mcp_configs}},
            "scope": ide_scope,
        }

        # Agent file for subagent registration
        agent_dir = ".cursor/agents" if ide_scope == "project" else "~/.cursor/agents"
        result["agent_file"] = {"path": f"{agent_dir}/{safe_name}.md", "content": cursor_agent_content}

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
        if skill_files:
            result["skill_files"] = skill_files
            result["skill_components"] = [s for s in skill_configs if s.get("git_url")]
        if ctx.compatibility_warnings:
            result["_warnings"] = ctx.compatibility_warnings

        return result


register_adapter(CursorAdapter())
