# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Kiro harness adapter for agent config generation."""

from __future__ import annotations

from loguru import logger as optic

from schemas.harness_registry import HARNESS_REGISTRY
from services.harness import ConfigContext, register_adapter
from services.harness.helpers import (
    _KIRO_EVENT_MAP,
    _collect_hook_script_files,
    _wrap_kiro_prompt,
)


class KiroAdapter:
    """Kiro harness adapter."""

    @property
    def harness_name(self) -> str:
        return "kiro"

    def format_config(self, ctx: ConfigContext) -> dict:
        optic.trace("ctx={}", ctx)
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

        kiro_spec = HARNESS_REGISTRY["kiro"]
        kiro_scope = options.get("scope", kiro_spec["default_scope"])

        # Determine scope-aware hooks dir
        hooks_dir = "~/.kiro/hooks" if kiro_scope == "user" else ".kiro/hooks"

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
                script_filename = hc.get("script_filename")
                if not cmd and script_filename:
                    cmd = f"{hooks_dir}/{script_filename}"
                elif not cmd:
                    continue
                elif script_filename:
                    cmd = f"{hooks_dir}/{script_filename}"
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

        agent_path = kiro_spec["agent_profile"][kiro_scope].format(name=safe_name)
        kiro_model = options.get("_resolved_model", None)

        content = {
            "name": safe_name,
            "description": (ctx.agent.description or safe_name).replace("\n", " ").strip()[:200],
            "prompt": _wrap_kiro_prompt(ctx.agent.prompt, safe_name),
            "mcpServers": mcp_configs,
            "tools": ["*"],
            "toolAliases": {},
            "allowedTools": [],
            "resources": [
                "file://AGENTS.md",
                "file://README.md",
                "skill://.kiro/skills/**/SKILL.md",
                "skill://~/.kiro/skills/**/SKILL.md",
            ],
            "hooks": hooks,
            "toolsSettings": {},
            "includeMcpJson": True,
            "model": kiro_model,
        }
        result: dict = {
            "agent_profile": {"path": agent_path, "content": content},
            "scope": kiro_scope,
        }

        if skill_configs:
            result["skill_components"] = skill_configs

        kiro_hook_files = _collect_hook_script_files(hook_configs, ctx.hook_listings, "kiro")
        if kiro_hook_files:
            # Fix paths for user scope
            if kiro_scope == "user":
                for hf in kiro_hook_files:
                    hf["path"] = hf["path"].replace(".kiro/hooks", "~/.kiro/hooks", 1)
            result["hook_files"] = kiro_hook_files

        warnings_combined = list(ctx.compatibility_warnings)
        warnings_combined.extend(options.get("_model_warnings") or [])
        if warnings_combined:
            result["_warnings"] = warnings_combined

        return result


# Auto-register on import
register_adapter(KiroAdapter())
