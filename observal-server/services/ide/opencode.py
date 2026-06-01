# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""OpenCode IDE adapter for agent config generation."""

from __future__ import annotations

from loguru import logger as optic

from schemas.ide_registry import IDE_REGISTRY
from services.ide import ConfigContext, register_adapter
from services.ide.helpers import _opencode_plugin_js


class OpenCodeAdapter:
    """OpenCode IDE adapter."""

    @property
    def ide_name(self) -> str:
        return "opencode"

    def format_config(self, ctx: ConfigContext) -> dict:
        optic.trace("ctx={}", ctx)
        safe_name = ctx.safe_name
        options = ctx.options
        mcp_configs = ctx.mcp_configs
        rules_content = ctx.rules_content

        opencode_spec = IDE_REGISTRY["opencode"]
        opencode_scope = options.get("scope", opencode_spec["default_scope"])

        opencode_configs = {}
        for k, v in mcp_configs.items():
            cmd_array = [v["command"], *v.get("args", [])]
            opencode_configs[k] = {"type": "local", "command": cmd_array}
            if "env" in v:
                opencode_configs[k]["env"] = v["env"]

        rules_path = opencode_spec["rules_file"][opencode_scope].format(name=safe_name)
        mcp_path = opencode_spec["mcp_config_path"].get(
            opencode_scope, next(iter(opencode_spec["mcp_config_path"].values()))
        )

        opencode_content: dict = {opencode_spec["mcp_servers_key"]: opencode_configs}
        opencode_model = options.get("_resolved_model")
        if opencode_model:
            opencode_content["model"] = opencode_model

        result: dict = {
            "rules_file": {"path": rules_path, "content": rules_content},
            "mcp_config": {"path": mcp_path, "content": opencode_content},
            "hooks_config": {
                "path": ".opencode/plugins/observal-plugin.mjs",
                "content": _opencode_plugin_js(),
            },
            "scope": opencode_scope,
        }

        warnings_combined = list(ctx.compatibility_warnings)
        warnings_combined.extend(options.get("_model_warnings") or [])
        if warnings_combined:
            result["_warnings"] = warnings_combined

        return result


register_adapter(OpenCodeAdapter())
