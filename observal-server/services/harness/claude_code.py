# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Claude Code harness adapter for agent config generation."""

from __future__ import annotations

from loguru import logger as optic

from schemas.harness_registry import HARNESS_REGISTRY
from services.harness import ConfigContext, register_adapter
from services.harness.helpers import (
    _claude_code_hooks_frontmatter_lines,
    _collect_hook_script_files,
    _model_name_to_frontmatter,
)


class ClaudeCodeAdapter:
    """Claude Code harness adapter."""

    @property
    def harness_name(self) -> str:
        return "claude-code"

    def format_config(self, ctx: ConfigContext) -> dict:
        optic.trace("ctx={}", ctx)
        safe_name = ctx.safe_name
        options = ctx.options
        mcp_configs = ctx.mcp_configs
        rules_content = ctx.rules_content
        hook_configs = ctx.hook_configs
        skill_configs = ctx.skill_configs
        setup_commands = []
        claude_mcps = {}
        for name, cfg in mcp_configs.items():
            if cfg.get("url") or cfg.get("type") in ("sse", "streamable-http"):
                # SSE/streamable-http entry: preserve as-is (url, headers, env)
                claude_mcps[name] = cfg
            else:
                cmd = cfg.get("command", "observal-shim")
                args = cfg.get("args", [])
                setup_commands.append(["claude", "mcp", "add", name, "--", cmd, *args])
                claude_mcps[name] = {"command": cmd, "args": args, "env": cfg.get("env", {})}

        scope = options.get("scope", HARNESS_REGISTRY["claude-code"]["default_scope"])
        tools = options.get("tools", "")
        color = options.get("color", "")

        # Model resolution
        if "_resolved_model" in options:
            model_choice = options.get("_resolved_model") or ""
        else:
            model_choice = options.get("model", "")
            if not model_choice or model_choice == "inherit":
                model_choice = _model_name_to_frontmatter(getattr(ctx.agent, "model_name", ""))

        # Build YAML frontmatter
        frontmatter_lines = [
            "---",
            f"name: {safe_name}",
        ]
        agent_desc = getattr(ctx.agent, "description", "") or ""
        if agent_desc:
            frontmatter_lines.append(f'description: "{agent_desc}"')
        if model_choice:
            frontmatter_lines.append(f"model: {model_choice}")
        if tools:
            frontmatter_lines.append(f"tools: {tools}")
        if color:
            frontmatter_lines.append(f"color: {color}")
        if claude_mcps:
            frontmatter_lines.append("mcpServers:")
            for mcp_name in claude_mcps:
                frontmatter_lines.append(f"  - {mcp_name}")
        frontmatter_lines.extend(_claude_code_hooks_frontmatter_lines(custom_hooks=hook_configs))
        frontmatter_lines.append("---")
        agent_content = "\n".join(frontmatter_lines) + "\n\n" + rules_content

        agent_path = HARNESS_REGISTRY["claude-code"]["agent_profile"][scope].format(name=safe_name)

        result: dict = {
            "agent_profile": {"path": agent_path, "content": agent_content},
            "mcp_config": claude_mcps,
            "mcp_setup_commands": setup_commands,
            "scope": scope,
        }
        if skill_configs:
            result["skill_components"] = skill_configs

        cc_hook_files = _collect_hook_script_files(hook_configs, ctx.hook_listings, "claude-code")
        if cc_hook_files:
            result["hook_files"] = cc_hook_files

        warnings_combined = list(ctx.compatibility_warnings)
        warnings_combined.extend(options.get("_model_warnings") or [])
        if warnings_combined:
            result["_warnings"] = warnings_combined

        return result


register_adapter(ClaudeCodeAdapter())
