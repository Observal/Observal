# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Antigravity CLI server-side config generator."""

from __future__ import annotations

from loguru import logger

from schemas.ide_registry import IDE_REGISTRY
from services.ide import ConfigContext, register_adapter


class AntigravityAdapter:
    """Antigravity CLI IDE adapter for agent config generation."""

    @property
    def ide_name(self) -> str:
        return "antigravity"

    def format_config(self, ctx: ConfigContext) -> dict:
        logger.debug("format_config: agent={}", ctx.safe_name)
        spec = IDE_REGISTRY["antigravity"]
        options = ctx.options
        scope = options.get("scope", spec["default_scope"])

        # MCP config
        mcp_path = spec["mcp_config_path"].get(scope, spec["mcp_config_path"]["project"])
        mcp_content = {spec["mcp_servers_key"]: ctx.mcp_configs}

        # Rules file
        rules_path = spec["rules_file"].get(scope, spec["rules_file"]["project"])
        rules_path = rules_path.replace("{name}", ctx.safe_name)

        # Skill files
        skill_files = []
        skill_path_template = spec["skill_file"].get(scope, spec["skill_file"]["project"])
        for skill in ctx.skill_configs:
            skill_name = skill.get("name", "unnamed")
            skill_path = skill_path_template.replace("{name}", skill_name)
            skill_files.append({"path": skill_path, "content": skill.get("content", "")})

        result: dict = {
            "rules_file": {"path": rules_path, "content": ctx.rules_content},
            "mcp_config": {"path": mcp_path, "content": mcp_content},
            "scope": scope,
        }

        if skill_files:
            result["skill_files"] = skill_files

        # Model choice
        model = options.get("_resolved_model")
        if model:
            mcp_content["model"] = model

        warnings = list(ctx.compatibility_warnings)
        warnings.extend(options.get("_model_warnings") or [])
        if warnings:
            result["_warnings"] = warnings

        return result


register_adapter(AntigravityAdapter())
