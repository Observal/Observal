# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Gemini CLI IDE adapter for agent config generation."""

from __future__ import annotations

from loguru import logger

from schemas.ide_registry import IDE_REGISTRY
from services.ide import ConfigContext, register_adapter
from services.ide.helpers import _gemini_hooks_config, _gemini_settings


class GeminiCliAdapter:
    """Gemini CLI IDE adapter."""

    @property
    def ide_name(self) -> str:
        logger.debug("ide_name called")
        return "gemini-cli"

    def format_config(self, ctx: ConfigContext) -> dict:
        logger.debug("format_config: ctx={}", ctx)
        options = ctx.options
        mcp_configs = ctx.mcp_configs
        rules_content = ctx.rules_content

        gemini_spec = IDE_REGISTRY["gemini-cli"]
        gemini_scope = options.get("scope", gemini_spec["default_scope"])
        rules_path = gemini_spec["rules_file"][gemini_scope]
        mcp_path = gemini_spec["mcp_config_path"][gemini_scope]
        hooks_path = gemini_spec["mcp_config_path"][gemini_scope]

        gemini_settings_content: dict = {"mcpServers": mcp_configs}
        gemini_model = options.get("_resolved_model")
        if gemini_model:
            gemini_settings_content["model"] = gemini_model

        result: dict = {
            "rules_file": {"path": rules_path, "content": rules_content},
            "mcp_config": {"path": mcp_path, "content": gemini_settings_content},
            "hooks_config": {
                "path": hooks_path,
                "content": _gemini_hooks_config(),
            },
            "gemini_settings_snippet": _gemini_settings(),
            "scope": gemini_scope,
        }

        warnings_combined = list(ctx.compatibility_warnings)
        warnings_combined.extend(options.get("_model_warnings") or [])
        if warnings_combined:
            result["_warnings"] = warnings_combined

        return result


register_adapter(GeminiCliAdapter())
