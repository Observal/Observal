# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Copilot CLI IDE adapter for agent config generation."""

from __future__ import annotations

from loguru import logger

from schemas.ide_registry import IDE_REGISTRY
from services.ide import ConfigContext, register_adapter
from services.ide.helpers import (
    _vscode_copilot_hooks_config,
    _vscode_copilot_hooks_frontmatter_lines,
)


class CopilotCliAdapter:
    """GitHub Copilot CLI IDE adapter."""

    @property
    def ide_name(self) -> str:
        logger.debug("ide_name called")
        return "copilot-cli"

    def format_config(self, ctx: ConfigContext) -> dict:
        logger.debug("format_config: ctx={}", ctx)
        safe_name = ctx.safe_name
        mcp_configs = ctx.mcp_configs
        rules_content = ctx.rules_content

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

        copilot_cli_spec = IDE_REGISTRY["copilot-cli"]

        frontmatter_lines = [
            "---",
            f"name: {safe_name}",
            "tools: ['*']",
        ]
        frontmatter_lines.extend(_vscode_copilot_hooks_frontmatter_lines())
        frontmatter_lines.append("---")
        agent_content = "\n".join(frontmatter_lines) + "\n\n" + rules_content

        result: dict = {
            "rules_file": {
                "path": f".github/agents/{safe_name}.agent.md",
                "content": agent_content,
            },
            "mcp_config": {
                "path": copilot_cli_spec["mcp_config_path"]["project"],
                "content": {copilot_cli_spec["mcp_servers_key"]: copilot_cli_configs},
            },
            "hooks_config": {
                "path": ".github/hooks/observal.json",
                "content": _vscode_copilot_hooks_config(),
            },
            "scope": copilot_cli_spec["default_scope"],
        }
        if ctx.compatibility_warnings:
            result["_warnings"] = ctx.compatibility_warnings

        return result


register_adapter(CopilotCliAdapter())
