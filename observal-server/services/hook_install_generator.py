# SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Generic hook install config generator for all supported IDEs.

This is SEPARATE from hook_config_generator.py which handles Observal's
own telemetry hooks (session_push). This module generates install config
for user-submitted registry hooks across all 8 IDEs.
"""

from __future__ import annotations

from loguru import logger as optic

from schemas.ide_registry import IDE_REGISTRY


def generate_hook_install_config(
    hook_listing,
    ide: str,
    server_url: str = "http://localhost:8000",
) -> dict:
    """Generate a complete install response for a registry hook.

    Returns a dict compatible with HookInstallResponse:
      - config_snippet: IDE-specific hook config
      - config_path: where the config lives
      - files: script files to write
      - requirements: install prerequisites
      - source_fetch: git fetch info for multi-file hooks
      - notes: human-readable notes
    """
    optic.debug("generating hook install config: hook={}, ide={}", hook_listing.name, ide)
    ide_info = IDE_REGISTRY.get(ide)
    if not ide_info:
        return {
            "config_snippet": {},
            "config_path": "",
            "files": [],
            "requirements": [],
            "source_fetch": None,
            "notes": [f"IDE '{ide}' is not recognized. Supported: {', '.join(IDE_REGISTRY.keys())}"],
        }

    hook_type = ide_info.get("hook_type")
    events_map = ide_info.get("hook_events_map", {})
    hook_config_path = ide_info.get("hook_config_path", {})
    hook_scripts_dir = ide_info.get("hook_scripts_dir", "")

    # Map canonical event to IDE-specific event
    event = str(getattr(hook_listing, "event", "") or "")
    ide_event = events_map.get(event)

    if not ide_event:
        supported = [k for k, v in events_map.items() if v]
        return {
            "config_snippet": {},
            "config_path": "",
            "files": [],
            "requirements": [],
            "source_fetch": None,
            "notes": [
                f"Event '{event}' is not supported by {ide_info['display_name']}.",
                f"Supported events: {', '.join(supported)}",
            ],
        }

    # OpenCode uses plugins, not command hooks - manual setup only
    if hook_type == "plugin":
        return _generate_plugin_instructions(hook_listing, ide_info, ide_event)

    # Build handler info
    handler_type = str(getattr(hook_listing, "handler_type", "command") or "command")
    handler_config = getattr(hook_listing, "handler_config", {}) or {}
    command = handler_config.get("command", "")
    timeout = handler_config.get("timeout")
    script_content = getattr(hook_listing, "script_content", None)
    script_filename = getattr(hook_listing, "script_filename", None)
    source_url = getattr(hook_listing, "source_url", None)
    source_path = getattr(hook_listing, "source_path", None)
    source_ref = getattr(hook_listing, "source_ref", None)
    resolved_sha = getattr(hook_listing, "resolved_sha", None)
    requirements = getattr(hook_listing, "requirements", None) or []

    # Determine script path and files to write
    files: list[dict] = []
    actual_command = command

    if script_content and script_filename:
        # Tier 2: single-file script - write to IDE's hooks dir
        script_path = f"{hook_scripts_dir}/{script_filename}"
        actual_command = script_path
        files.append(
            {
                "path": script_path,
                "content": script_content,
                "executable": True,
            }
        )

    # Build source_fetch for Tier 3 (multi-file git-sourced)
    source_fetch = None
    if source_url and source_path and not script_content:
        source_fetch = {
            "url": source_url,
            "path": source_path,
            "ref": source_ref or "main",
            "sha": resolved_sha,
            "target_dir": f"{hook_scripts_dir}/{hook_listing.name}",
        }
        actual_command = f"{hook_scripts_dir}/{hook_listing.name}/{command}"

    # Generate config snippet based on IDE format
    config_snippet = _build_config_snippet(ide, ide_info, ide_event, handler_type, actual_command, timeout)

    # Determine config path
    config_path_val = ""
    if hook_config_path:
        config_path_val = hook_config_path.get("project", "") or hook_config_path.get("user", "") or ""
        if "{name}" in config_path_val:
            config_path_val = config_path_val.replace("{name}", hook_listing.name)

    # Notes
    notes: list[str] = []
    if ide == "claude-code":
        notes.append("Also works in Cursor via Third Party Hooks (enable in Cursor Settings → Features).")

    return {
        "config_snippet": config_snippet,
        "config_path": config_path_val,
        "files": files,
        "requirements": requirements,
        "source_fetch": source_fetch,
        "notes": notes,
    }


def _build_config_snippet(
    ide: str,
    ide_info: dict,
    ide_event: str,
    handler_type: str,
    command: str,
    timeout: int | None,
) -> dict:
    """Build the IDE-specific config snippet."""

    optic.debug("_build_config_snippet: ide={}, ide_info={}", ide, ide_info)
    if ide == "claude-code":
        hook_entry: dict = {"type": handler_type, "command": command}
        if timeout:
            hook_entry["timeout"] = timeout
        return {"hooks": {ide_event: [{"matcher": "*", "hooks": [hook_entry]}]}}

    if ide == "cursor":
        hook_entry = {"command": command}
        return {"version": 1, "hooks": {ide_event: [hook_entry]}}

    if ide in ("kiro", "kiro-cli"):
        hook_entry = {"command": command}
        return {"hooks": {ide_event: [hook_entry]}}

    if ide == "gemini-cli":
        hook_entry = {"matcher": "*", "command": command}
        if timeout:
            hook_entry["timeout"] = timeout
        return {"hooks": {ide_event: [hook_entry]}}

    if ide in ("copilot", "copilot-cli"):
        hook_entry = {"command": command}
        return {"hooks": {ide_event: [hook_entry]}}

    if ide == "codex":
        # TOML format represented as dict
        return {
            "hooks": {ide_event: {"command": command}},
            "_format": "toml",
            "_note": f"Add to .codex/config.toml under [hooks.{ide_event}]",
        }

    # Fallback
    hook_entry = {"command": command}
    if timeout:
        hook_entry["timeout"] = timeout
    return {"hooks": {ide_event: [hook_entry]}}


def _generate_plugin_instructions(hook_listing, ide_info: dict, ide_event: str) -> dict:
    """Generate manual setup instructions for plugin-based IDEs (OpenCode)."""
    optic.debug("_generate_plugin_instructions: hook_listing={}, ide_info={}", hook_listing, ide_info)
    handler_config = getattr(hook_listing, "handler_config", {}) or {}
    command = handler_config.get("command", "")

    return {
        "config_snippet": {
            "_manual_setup": True,
            "_instructions": [
                "OpenCode uses a plugin system for hooks.",
                f"Create a plugin file in .opencode/plugins/{hook_listing.name}.ts",
                f"Register the '{ide_event}' event handler.",
                f"Command to execute: {command}",
            ],
            "event": ide_event,
            "command": command,
        },
        "config_path": f".opencode/plugins/{hook_listing.name}.ts",
        "files": [],
        "requirements": getattr(hook_listing, "requirements", None) or [],
        "source_fetch": None,
        "notes": [
            "OpenCode requires a TypeScript plugin. See https://opencode.ai/docs/plugins/ for the plugin API.",
        ],
    }
