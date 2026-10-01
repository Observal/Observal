# SPDX-FileCopyrightText: 2026 SrihariLegend <sriharilegend23@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""DeepSeek Harness config generation: user Cordis patches and on-demand skills."""

from __future__ import annotations

import hashlib
import re

import yaml

from observal_shared.harness_registry import HARNESS_REGISTRY
from services.harness import BaseHarnessAdapter, ConfigContext, McpConfigContext, register_adapter
from services.harness.helpers import _collect_hook_script_files, _merge_hook_components_into_config
from services.shared.utils import sanitize_name

_HOOK_PATH = "~/.dsh/observal/hooks.json"
_HOOK_PLUGIN = {
    "id": "observal-hooks",
    "name": "@deepseek-ai/dsh-hooks-claude-code",
    "config": {"configPath": _HOOK_PATH},
}
_MCP_PLUGIN = "@deepseek-ai/dsh-mcp-client"
_COLLECTOR = {
    "id": "observal-session-collector",
    "name": "~/.dsh/observal/collector.mjs",
    "config": {"pythonPath": "<runtime-python>", "dshHome": "<runtime-dsh-home>"},
}
_VALID_NAME = re.compile(r"[A-Za-z0-9_-]{1,32}\Z")


def _server_name(name: str) -> str:
    """Map arbitrary component names to stable, distinct native server identifiers."""
    if _VALID_NAME.fullmatch(name):
        return name
    safe = re.sub(r"[^A-Za-z0-9_-]", "-", name).strip("-_")[:23] or "mcp"
    digest = hashlib.sha256(name.encode("utf-8")).hexdigest()[:8]
    return f"{safe}-{digest}"


def _mcp_plugin(name: str, entry: dict) -> dict:
    server_name = _server_name(name)
    transport = entry.get("transport") or entry.get("type") or ""
    if transport == "sse":
        raise ValueError(f"DeepSeek Harness does not support legacy SSE MCP transport: {name}")
    if entry.get("url"):
        if transport not in ("", "streamable-http", "streamable_http"):
            raise ValueError(f"Unsupported DeepSeek MCP transport: {transport}")
        config = {
            "serverName": server_name,
            "transport": "streamable-http",
            "url": entry["url"],
            "headers": dict(entry.get("headers") or {}),
        }
    else:
        if transport not in ("", "stdio"):
            raise ValueError(f"Unsupported DeepSeek MCP transport: {transport}")
        if not entry.get("command"):
            raise ValueError(f"DeepSeek stdio MCP requires a command: {name}")
        config = {
            "serverName": server_name,
            "transport": "stdio",
            "command": entry["command"],
            "args": list(entry.get("args") or []),
            "env": dict(entry.get("env") or {}),
        }
    return {"id": f"observal-mcp-{server_name}", "name": _MCP_PLUGIN, "config": config}


def _patches(entries: dict[str, dict], *, with_hooks: bool = False) -> list[dict]:
    """Keep each owned plugin in its own insert action for lossless client merging."""
    patches = [{"insert": [dict(_COLLECTOR)]}]
    if with_hooks:
        patches.append({"insert": [dict(_HOOK_PLUGIN)]})
    used = {"observal-session-collector", "observal-hooks"}
    for name, entry in entries.items():
        plugin = _mcp_plugin(name, entry)
        if plugin["id"] in used:
            raise ValueError(f"DeepSeek MCP names normalize to the same identifier: {name}")
        used.add(plugin["id"])
        patches.append({"insert": [plugin]})
    return patches


class DeepSeekAdapter(BaseHarnessAdapter):
    """Generate native dsh patch rows without changing model selection or other profiles."""

    @property
    def harness_name(self) -> str:
        return "deepseek"

    def agent_mcp_entry(self, ctx: McpConfigContext) -> dict:
        entry: dict = {"transport": ctx.transport, "env": dict(ctx.server_env)}
        if ctx.url:
            entry.update({"url": ctx.url, "headers": dict(ctx.headers)})
        else:
            entry.update({"command": ctx.command, "args": list(ctx.args)})
        # _build_mcp_configs adds the agent ID to the entry's env before
        # format_config wraps it in a native Cordis insert action.
        return entry

    def format_mcp_config(self, ctx: McpConfigContext) -> dict:
        return {
            "path": HARNESS_REGISTRY["deepseek"]["mcp_config"]["user"],
            "content": [{"insert": [_mcp_plugin(ctx.name, self.agent_mcp_entry(ctx))]}],
            "_note": "Merge this Observal-owned insert into the user DSH_HOME/cordis.patch.yml; keep other patches intact.",
        }

    def format_hook_component(self, command: str) -> dict:
        return {"hooks": [{"type": "command", "command": command}]}

    def format_hook_install_snippet(self, event: str, handler_type: str, command: str, timeout: int | None) -> dict:
        if handler_type != "command":
            raise ValueError("DeepSeek's Claude-compatible hook bridge supports command hooks only")
        hook = {"type": "command", "command": command}
        if timeout:
            hook["timeout"] = timeout
        return {
            "hooks": {event: [{"hooks": [hook]}]},
            "_note": (
                "Merge into DSH_HOME/observal/hooks.json, and activate the "
                "@deepseek-ai/dsh-hooks-claude-code plugin (id observal-hooks) in "
                "DSH_HOME/cordis.patch.yml with config.configPath pointing to the hooks JSON. "
                "The JSON alone does not activate hooks."
            ),
        }

    def hook_install_notes(self) -> list[str]:
        return [
            "The user DSH_HOME/cordis.patch.yml must insert @deepseek-ai/dsh-hooks-claude-code "
            "(id observal-hooks) with config.configPath pointing to DSH_HOME/observal/hooks.json. "
            "The hooks JSON does not activate itself."
        ]

    def format_hook_telemetry(self, hook_listing, server_url: str, platform: str) -> dict:
        event = str(hook_listing.event)
        if event not in HARNESS_REGISTRY["deepseek"]["hook_events_map"]:
            raise ValueError(f"Unsupported DeepSeek hook event: {event}")
        return {
            "_note": "DeepSeek telemetry is collected by Observal's native plugin. "
            "Run `observal doctor patch --harness deepseek` to install it; no command hook is needed."
        }

    def format_config(self, ctx: ConfigContext) -> dict:
        spec = HARNESS_REGISTRY["deepseek"]
        scope = ctx.options.get("scope") or spec["default_scope"]
        if scope not in spec["scopes"]:
            raise ValueError(f"Unsupported DeepSeek scope: {scope}")
        skill_name = f"observal-{ctx.safe_name}"
        description = (getattr(ctx.agent, "description", "") or "").strip().split("\n", 1)[0][:200]
        if not description:
            description = f"Observal agent {ctx.safe_name}"
        frontmatter = yaml.safe_dump(
            {"name": skill_name, "description": description}, sort_keys=False, allow_unicode=True
        )
        content = f"---\n{frontmatter}---\n\n{ctx.rules_content.rstrip()}\n"
        hooks_content: dict = {"hooks": {}}
        for hook in ctx.hook_configs:
            if hook.get("handler_type", "command") != "command":
                raise ValueError("DeepSeek's Claude-compatible hook bridge supports command hooks only")
            if hook.get("event") not in spec["hook_events_map"]:
                raise ValueError(f"Unsupported DeepSeek hook event: {hook.get('event')}")
        _merge_hook_components_into_config(hooks_content, ctx.hook_configs, "deepseek")

        mcp_configs = dict(ctx.mcp_configs)
        # The shared builder only carries external command/args fields. Retain
        # external URL and transport metadata here without changing other adapters.
        for external in getattr(ctx.agent, "external_mcps", None) or []:
            name = sanitize_name(external.get("name", ""))
            if name not in mcp_configs:
                continue
            entry = dict(mcp_configs[name])
            if external.get("url"):
                entry.update(
                    url=external["url"],
                    headers=dict(external.get("headers") or {}),
                    transport=external.get("transport") or external.get("type") or "streamable-http",
                )
            elif external.get("transport") or external.get("type"):
                entry["transport"] = external.get("transport") or external["type"]
            mcp_configs[name] = entry

        result: dict = {
            "agent_profile": {"path": spec["agent_profile"][scope].format(name=ctx.safe_name), "content": content},
            "mcp_config": {
                "path": spec["mcp_config"]["user"],
                "content": _patches(mcp_configs, with_hooks=bool(hooks_content["hooks"])),
            },
            "scope": scope,
        }
        if hooks_content["hooks"]:
            result["hooks_config"] = {"path": spec["hooks"]["user"], "content": hooks_content, "merge": True}
        hook_files = _collect_hook_script_files(ctx.hook_configs, ctx.hook_listings, "deepseek")
        if hook_files:
            result["hook_files"] = hook_files
        if ctx.skill_configs:
            result["skill_components"] = ctx.skill_configs
        warnings = list(ctx.compatibility_warnings)
        if scope == "project":
            warnings.append(
                "DeepSeek MCPs and hooks activate from the user DSH_HOME for every profile, "
                "even when this agent skill is project-local."
            )
        warnings.append("DeepSeek agent instructions are an on-demand skill; invoke it explicitly.")
        if warnings:
            result["_warnings"] = warnings
        return result


register_adapter(DeepSeekAdapter())
