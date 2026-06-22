# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Antigravity CLI server-side config generator."""

from __future__ import annotations

from loguru import logger

from schemas.harness_registry import HARNESS_REGISTRY
from services.harness import ConfigContext, register_adapter


class AntigravityAdapter:
    """Antigravity CLI harness adapter for agent config generation."""

    @property
    def harness_name(self) -> str:
        return "antigravity"

    def format_config(self, ctx: ConfigContext) -> dict:
        logger.debug("format_config: agent={}", ctx.safe_name)
        spec = HARNESS_REGISTRY["antigravity"]
        options = ctx.options
        scope = options.get("scope", spec["default_scope"])
        agent_path = spec["agent_profile"][scope].format(name=ctx.safe_name)
        description = (getattr(ctx.agent, "description", "") or ctx.safe_name).replace("\n", " ").strip()[:200]
        result: dict = {
            "agent_profile": {
                "path": agent_path,
                "content": {
                    "name": ctx.safe_name,
                    "description": description,
                    "system_prompt": ctx.rules_content,
                    "mcpServers": ctx.mcp_configs,
                    "tools": ["*"],
                    "model": options.get("_resolved_model"),
                },
            },
            "scope": scope,
        }

        if ctx.mcp_configs:
            mcp_path = spec["mcp_config"].get(scope, spec["mcp_config"]["user"])
            result["mcp_config"] = {"path": mcp_path, "content": {spec["mcp_servers_key"]: ctx.mcp_configs}}

        skills = []
        skill_path_template = spec["skills"].get(scope, spec["skills"]["user"])
        for skill in ctx.skill_configs:
            skill_name = skill.get("name", "unnamed")
            skill_path = skill_path_template.replace("{name}", skill_name)
            content = (
                skill.get("skill_md_content")
                or f"---\nname: {skill_name}\ndescription: {skill.get('description', '')}\n---\n"
            )
            skills.append({"path": skill_path, "content": content})
        if skills:
            result["skills"] = skills

        warnings = list(ctx.compatibility_warnings)
        warnings.extend(options.get("_model_warnings") or [])
        if warnings:
            result["_warnings"] = warnings

        return result


register_adapter(AntigravityAdapter())
