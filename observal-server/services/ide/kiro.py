# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Kiro IDE adapter for agent config generation."""

from __future__ import annotations

from loguru import logger

from schemas.ide_registry import IDE_REGISTRY
from services.ide import ConfigContext, register_adapter
from services.ide.helpers import (
    _KIRO_EVENT_MAP,
    _collect_hook_script_files,
    _generate_skill_file,
    _wrap_kiro_prompt,
)


class KiroAdapter:
    """Kiro IDE adapter."""

    @property
    def ide_name(self) -> str:
        logger.debug("ide_name called")
        return "kiro"

    def format_config(self, ctx: ConfigContext) -> dict:
        logger.debug("format_config: ctx={}", ctx)
        safe_name = ctx.safe_name
        options = ctx.options
        platform = ctx.platform
        mcp_configs = ctx.mcp_configs
        hook_configs = ctx.hook_configs
        skill_configs = ctx.skill_configs

        # Telemetry via JSONL session push
        if platform == "win32":
            push_cmd = "python -m observal_cli.hooks.kiro_session_push"
        else:
            push_cmd = "python3 -m observal_cli.hooks.kiro_session_push"
        hooks: dict = {
            "userPromptSubmit": [{"command": push_cmd}],
            "stop": [{"command": push_cmd}],
        }

        # Merge custom hook components
        for hc in hook_configs:
            event = hc.get("event")
            if not event:
                continue
            kiro_event = _KIRO_EVENT_MAP.get(event, event)
            handler_type = hc.get("handler_type", "command")
            handler_config = hc.get("handler_config", {})
            if handler_type == "command":
                cmd = handler_config.get("command", "")
                if not cmd:
                    continue
                script_filename = hc.get("script_filename")
                if script_filename and cmd == script_filename:
                    cmd = f".kiro/hooks/{script_filename}"
                entry: dict = {"command": cmd}
                if kiro_event in ("preToolUse", "postToolUse"):
                    entry["matcher"] = handler_config.get("matcher", "*")
                hooks.setdefault(kiro_event, []).append(entry)
            elif handler_type == "http":
                url = handler_config.get("url", "")
                if not url:
                    continue
                entry = {"command": f"curl -s -X POST -H 'Content-Type: application/json' -d @- {url}"}
                if kiro_event in ("preToolUse", "postToolUse"):
                    entry["matcher"] = handler_config.get("matcher", "*")
                hooks.setdefault(kiro_event, []).append(entry)

        kiro_spec = IDE_REGISTRY["kiro"]
        kiro_scope = options.get("scope", kiro_spec["default_scope"])
        agent_path = kiro_spec["rules_file"][kiro_scope].format(name=safe_name)
        kiro_model = options.get("_resolved_model", None)

        result: dict = {
            "agent_file": {
                "path": agent_path,
                "content": {
                    "name": safe_name,
                    "prompt": _wrap_kiro_prompt(ctx.agent.prompt, safe_name),
                    "mcpServers": mcp_configs,
                    "tools": ["*"],
                    "toolAliases": {},
                    "allowedTools": [],
                    "resources": [
                        "file://AGENTS.md",
                        "file://README.md",
                        "skill://.kiro/skills/*/SKILL.md",
                        "skill://~/.kiro/skills/*/SKILL.md",
                    ],
                    "hooks": hooks,
                    "toolsSettings": {},
                    "includeMcpJson": True,
                    "model": kiro_model,
                },
            },
            "scope": kiro_scope,
        }

        skill_files = [_generate_skill_file(s, "kiro") for s in skill_configs]
        skill_files = [f for f in skill_files if f]
        if skill_files:
            result["skill_files"] = skill_files
            result["skill_components"] = [s for s in skill_configs if s.get("git_url")]

        kiro_hook_files = _collect_hook_script_files(hook_configs, ctx.hook_listings, "kiro")
        if kiro_hook_files:
            result["hook_files"] = kiro_hook_files

        warnings_combined = list(ctx.compatibility_warnings)
        warnings_combined.extend(options.get("_model_warnings") or [])
        if warnings_combined:
            result["_warnings"] = warnings_combined

        return result


# Auto-register on import
register_adapter(KiroAdapter())
