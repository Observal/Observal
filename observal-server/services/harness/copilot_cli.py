# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-FileCopyrightText: 2026 Naraen Rammoorthi <naraen13@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""Copilot CLI harness adapter for agent config generation."""

from __future__ import annotations

from loguru import logger as optic

from observal_shared.harness_registry import HARNESS_REGISTRY
from services.harness import BaseHarnessAdapter, ConfigContext, McpConfigContext, register_adapter
from services.harness.helpers import (
    _collect_hook_script_files,
    _generate_prompt_files,
    _generate_skill,
    _merge_hook_components_into_config,
)

# Session push command used in generated hook files
_SESSION_PUSH_CMD = "python3 -m observal_cli.hooks.session_push --harness copilot-cli"
_SESSION_PUSH_CMD_WIN = "python -m observal_cli.hooks.session_push --harness copilot-cli"

# Events that Copilot CLI hooks support
_COPILOT_CLI_HOOK_EVENTS = (
    "sessionStart",
    "sessionEnd",
    "userPromptSubmitted",
    "preToolUse",
    "postToolUse",
)


def _copilot_cli_hooks_config() -> dict:
    """Build .github/hooks/observal.json content for Copilot CLI.

    Uses the Copilot CLI hook file format:
    {"version": 1, "hooks": {"eventName": [{"type": "command", "bash": "...", "powershell": "...", "timeoutSec": 5}]}}
    """
    hooks: dict[str, list[dict]] = {}
    for event in _COPILOT_CLI_HOOK_EVENTS:
        hooks[event] = [
            {"type": "command", "bash": _SESSION_PUSH_CMD, "powershell": _SESSION_PUSH_CMD_WIN, "timeoutSec": 5}
        ]
    return {"version": 1, "hooks": hooks}


class CopilotCliAdapter(BaseHarnessAdapter):
    """GitHub Copilot CLI harness adapter."""

    @property
    def harness_name(self) -> str:
        return "copilot-cli"

    def format_hook_install_snippet(self, event: str, handler_type: str, command: str, timeout: int | None) -> dict:
        return {"hooks": {event: [{"command": command}]}}

    def format_hook_component(self, command: str) -> dict:
        return {"type": "command", "command": command}

    def emits_prompt_files(self) -> bool:
        return True

    def format_mcp_config(self, ctx: McpConfigContext) -> dict:
        if ctx.url:
            entry = {**ctx.standard_entry(), "tools": ["*"]}
        elif ctx.proxy_url:
            entry = {"type": "sse", "url": ctx.proxy_url, "env": ctx.server_env, "tools": ["*"]}
        else:
            entry = {"type": "stdio", **ctx.standard_entry(), "tools": ["*"]}
        return {"mcpServers": {ctx.name: entry}}

    def format_config(self, ctx: ConfigContext) -> dict:
        optic.trace("ctx={}", ctx)
        safe_name = ctx.safe_name
        mcp_configs = ctx.mcp_configs
        rules_content = ctx.rules_content
        hook_configs = ctx.hook_configs
        skill_configs = ctx.skill_configs

        # Build MCP config entries with Copilot CLI format
        copilot_cli_configs = {}
        for k, v in mcp_configs.items():
            if v.get("url"):
                transport_type = v.get("type", "sse")
                copilot_cli_configs[k] = {"type": transport_type, "url": v["url"], "tools": ["*"]}
                if "env" in v:
                    copilot_cli_configs[k]["env"] = v["env"]
            else:
                copilot_cli_configs[k] = {
                    "type": "stdio",
                    "command": v["command"],
                    "args": v.get("args", []),
                    "tools": ["*"],
                }
                if "env" in v:
                    copilot_cli_configs[k]["env"] = v["env"]

        copilot_cli_spec = HARNESS_REGISTRY["copilot-cli"]

        # Build .agent.md with YAML frontmatter
        agent_desc = getattr(ctx.agent, "description", "") or safe_name
        frontmatter_lines = [
            "---",
            f"name: {safe_name}",
            f'description: "{agent_desc}"',
            "tools: ['*']",
        ]
        # Add mcp-servers to frontmatter if present
        if copilot_cli_configs:
            frontmatter_lines.append("mcp-servers:")
            for mcp_name in copilot_cli_configs:
                frontmatter_lines.append(f"  {mcp_name}:")
                cfg = copilot_cli_configs[mcp_name]
                if cfg.get("type"):
                    frontmatter_lines.append(f"    type: {cfg['type']}")
                if cfg.get("command"):
                    frontmatter_lines.append(f"    command: {cfg['command']}")
                if cfg.get("args"):
                    args_str = ", ".join(str(a) for a in cfg["args"])
                    frontmatter_lines.append(f"    args: [{args_str}]")
                if cfg.get("url"):
                    frontmatter_lines.append(f"    url: {cfg['url']}")
        frontmatter_lines.append("---")
        agent_content = "\n".join(frontmatter_lines) + "\n\n" + rules_content

        # Build hooks config in Copilot CLI format
        hooks_content = _copilot_cli_hooks_config()
        _merge_hook_components_into_config(hooks_content, hook_configs, "copilot-cli")

        # Build skill files
        skills = [_generate_skill(s, "copilot-cli", "project") for s in skill_configs]
        skills = [f for f in skills if f]

        result: dict = {
            "agent_profile": {
                "path": f".github/agents/{safe_name}.agent.md",
                "content": agent_content,
            },
            "mcp_config": {
                "path": copilot_cli_spec["mcp_config"]["project"],
                "content": {copilot_cli_spec["mcp_servers_key"]: copilot_cli_configs},
            },
            "hooks_config": {
                "path": ".github/hooks/observal.json",
                "content": hooks_content,
            },
            "scope": copilot_cli_spec["default_scope"],
        }

        # Hook script files
        hook_files = _collect_hook_script_files(hook_configs, ctx.hook_listings, "copilot-cli")
        if hook_files:
            result["hook_files"] = hook_files
        # Native Copilot prompt files (.github/prompts/*.prompt.md)
        prompt_files = _generate_prompt_files(ctx.prompt_listings, ctx.agent, ctx.component_names)
        if prompt_files:
            result["prompt_files"] = prompt_files
        if skills:
            result["skills"] = skills
            result["skill_components"] = [s for s in skill_configs if s.get("git_url")]
        if ctx.compatibility_warnings:
            result["_warnings"] = ctx.compatibility_warnings

        return result


register_adapter(CopilotCliAdapter())
