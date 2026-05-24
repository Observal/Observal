# SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Pi IDE adapter for agent config generation.

Pi is harness-centric: `observal pull` writes AGENTS.md which becomes pi's
entire system prompt, effectively reconfiguring the whole agent runtime.
MCP servers are written to ~/.pi/agent/mcp.json (read by pi-mcp-adapter).
Skills go to .pi/skills/ or ~/.pi/agent/skills/.
"""

from __future__ import annotations

from loguru import logger

from schemas.ide_registry import IDE_REGISTRY
from services.ide import ConfigContext, register_adapter
from services.ide.helpers import _generate_skill_file


class PiAdapter:
    """Pi IDE adapter - harness-centric config generation."""

    @property
    def ide_name(self) -> str:
        logger.debug("PiAdapter.ide_name called")
        return "pi"

    def format_config(self, ctx: ConfigContext) -> dict:
        """Format config for Pi.

        Pi uses:
        - AGENTS.md (project) or ~/.pi/agent/AGENTS.md (user) for the system prompt
        - .pi/mcp.json or ~/.pi/agent/mcp.json for MCP servers (pi-mcp-adapter)
        - .pi/skills/{name}/SKILL.md for skills
        """
        logger.debug("PiAdapter.format_config: agent={}", ctx.safe_name)
        options = ctx.options
        scope = options.get("scope", IDE_REGISTRY["pi"]["default_scope"])

        result: dict = {}

        # ── Rules / Agent file (AGENTS.md) ──
        if ctx.rules_content:
            rules_spec = IDE_REGISTRY["pi"]["rules_file"]
            rules_path = rules_spec.get(scope, rules_spec.get("user", "AGENTS.md"))
            result["rules_file"] = {
                "path": rules_path,
                "content": ctx.rules_content,
            }

        # ── MCP config (for pi-mcp-adapter) ──
        if ctx.mcp_configs:
            mcp_path_spec = IDE_REGISTRY["pi"]["mcp_config_path"]
            mcp_path = mcp_path_spec.get(scope, mcp_path_spec.get("user"))
            if mcp_path:
                result["mcp_config"] = {
                    "path": mcp_path,
                    "content": {"mcpServers": ctx.mcp_configs},
                }

        # ── Skills ──
        skill_files = []
        for skill in ctx.skill_configs:
            entry = _generate_skill_file(skill, "pi")
            if entry:
                skill_files.append(entry)
        if skill_files:
            result["skill_files"] = skill_files

        # Pi doesn't use command-based hooks - telemetry is via observal-pi
        # No hook files to generate.

        return result


register_adapter(PiAdapter())
