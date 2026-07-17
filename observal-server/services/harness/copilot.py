# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-FileCopyrightText: 2026 Naraen Rammoorthi <naraen13@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""Copilot (VS Code) harness adapter for agent config generation.

Copilot in VS Code does not support hooks. Telemetry flows via OTel export
(opt-in) and MCP shim wrapping (always-on). This adapter generates:
- .github/agents/{name}.agent.md (agent file with YAML frontmatter)
- .vscode/mcp.json (MCP server config with "servers" key)
"""

from __future__ import annotations

from loguru import logger as optic

from schemas.harness_registry import HARNESS_REGISTRY
from services.harness import ConfigContext, register_adapter
from services.harness.helpers import _generate_prompt_files


class CopilotAdapter:
    """GitHub Copilot (VS Code) harness adapter."""

    @property
    def harness_name(self) -> str:
        return "copilot"

    def format_config(self, ctx: ConfigContext) -> dict:
        optic.trace("ctx={}", ctx)
        safe_name = ctx.safe_name
        mcp_configs = ctx.mcp_configs
        rules_content = ctx.rules_content

        copilot_configs = {}
        for k, v in mcp_configs.items():
            if v.get("url"):
                transport_type = v.get("type", "sse")
                copilot_configs[k] = {"type": transport_type, "url": v["url"]}
                if "env" in v:
                    copilot_configs[k]["env"] = v["env"]
            else:
                copilot_configs[k] = {"type": "stdio", "command": v["command"], "args": v.get("args", [])}
                if "env" in v:
                    copilot_configs[k]["env"] = v["env"]

        copilot_spec = HARNESS_REGISTRY["copilot"]

        agent_desc = getattr(ctx.agent, "description", "") or safe_name
        frontmatter_lines = [
            "---",
            f"name: {safe_name}",
            f'description: "{agent_desc}"',
            "target: vscode",
            "tools: ['*']",
            "---",
        ]
        agent_content = "\n".join(frontmatter_lines) + "\n\n" + rules_content

        result: dict = {
            "agent_profile": {
                "path": f".github/agents/{safe_name}.agent.md",
                "content": agent_content,
            },
            "mcp_config": {
                "path": copilot_spec["mcp_config"]["project"],
                "content": {copilot_spec["mcp_servers_key"]: copilot_configs},
            },
            "scope": copilot_spec["default_scope"],
        }
        # Native Copilot prompt files (.github/prompts/*.prompt.md)
        prompt_files = _generate_prompt_files(ctx.prompt_listings, ctx.agent, ctx.component_names)
        if prompt_files:
            result["prompt_files"] = prompt_files
        if ctx.compatibility_warnings:
            result["_warnings"] = ctx.compatibility_warnings

        return result


register_adapter(CopilotAdapter())
