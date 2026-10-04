# SPDX-FileCopyrightText: 2026 Observal Contributors
# SPDX-License-Identifier: Apache-2.0

"""Exact single-profile plan for the normal Claude Code agent pull writer."""

from __future__ import annotations

import json
import os
import stat
import sys
from pathlib import Path

from observal_cli import lockfile
from observal_cli.shared.utils import sanitize_name

MAX_BYTES = 2 * 1024 * 1024
DELEGATION_ARGS = ["-m", "observal_cli.delegation.mcp_server", "--harness", "claude-code"]


class ClaudePlanError(ValueError):
    """This release or local install needs explicit manual review."""


def profile(item: dict, old_files: dict[str, str]) -> Path:
    """Only an existing, solely owned user profile can be replaced."""
    name = item.get("local_name")
    if not isinstance(name, str) or not name or name != sanitize_name(name) or Path(name).name != name:
        raise ClaudePlanError("The saved Claude Code profile name is ambiguous; update manually.")
    claude_home = Path.home() / ".claude"
    configured_home = os.environ.get("CLAUDE_CONFIG_DIR")
    if configured_home and Path(configured_home).expanduser() != claude_home:
        raise ClaudePlanError("Claude Code uses a different config directory; update manually.")
    file = claude_home / "agents" / f"{name}.md"
    if set(old_files) != {str(file)} or any(part.is_symlink() for part in (file, *file.parents)) or not file.is_file():
        raise ClaudePlanError("The agent does not own exactly one existing Claude Code profile; update manually.")
    root = item.get("directory")
    if not isinstance(root, str) or not Path(root).is_absolute() or not Path(root).is_dir():
        raise ClaudePlanError("The original pull directory is unavailable; update manually.")
    # Another registry may have claimed this destination in its installed
    # record even if it has no baseline. Don't infer sole ownership from ours.
    registry = lockfile.current_registry_url()
    try:
        for url, section in lockfile.read_lockfile().get("registries", {}).items():
            for entry in section.get("harnesses", {}).get("claude-code", {}).get("agents", []):
                if entry.get("scope") != "user":
                    continue
                if (
                    lockfile.normalize_server_url(url) == registry
                    and entry.get("id") == item.get("id")
                    and entry.get("directory") == item.get("directory")
                    and entry.get("local_name") == name
                ):
                    continue
                local = entry.get("local_name")
                display = entry.get("name")
                if not isinstance(local, str) or not local:
                    # A legacy record without a local path cannot prove that
                    # it does not own this destination.
                    raise ClaudePlanError("Another agent has unknown Claude Code profile ownership; update manually.")
                if sanitize_name(local) == name or (isinstance(display, str) and sanitize_name(display) == name):
                    raise ClaudePlanError("Another installed agent claims this Claude Code profile; update manually.")
    except (OSError, RuntimeError, TypeError, KeyError, ValueError) as error:
        raise ClaudePlanError("Profile ownership cannot be checked; update manually.") from error
    return file


def _existing_delegation(snippet: dict, root: str) -> None:
    """The normal pull's only setup command must already be an exact no-op.

    Claude Code registers this MCP in its *local project* config, which is
    shared with other agents and is not in this profile's ownership baseline.
    Never execute setup or edit that config during an automatic profile update.
    """
    expected = {"command": sys.executable, "args": DELEGATION_ARGS, "env": {}}
    command = ["claude", "mcp", "add", "observal-agents", "--", sys.executable, *DELEGATION_ARGS]
    if snippet["mcp_config"] != {"observal-agents": expected} or snippet["mcp_setup_commands"] != [command]:
        raise ClaudePlanError("The release changes MCP registration; update manually.")
    custom = os.environ.get("CLAUDE_CONFIG_DIR")
    config_root = Path(custom).expanduser() if custom else Path.home()
    if not config_root.is_absolute():
        raise ClaudePlanError("The Claude Code config location is ambiguous; update manually.")
    settings = config_root / ".claude.json"
    if any(part.is_symlink() for part in (settings, *settings.parents)):
        raise ClaudePlanError("The Claude Code config crosses a symbolic link; update manually.")
    try:
        info = settings.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_BYTES or stat.S_IMODE(info.st_mode) & ~0o777:
            raise ClaudePlanError("The existing Claude Code MCP config is unsafe; update manually.")
        data = json.loads(settings.read_text(encoding="utf-8"))
        registered = data["projects"][root]["mcpServers"]["observal-agents"]
    except (OSError, ValueError, TypeError, KeyError, UnicodeError) as error:
        raise ClaudePlanError(
            "The existing Claude Code MCP registration cannot be verified; update manually."
        ) from error
    if registered != {"type": "stdio", **expected}:
        raise ClaudePlanError("The existing Claude Code MCP registration differs; update manually.")


def plan(snippet: object, item: dict, old_files: dict[str, str]) -> dict[Path, bytes]:
    """Reproduce the normal writer's only output, without invoking it."""
    file = profile(item, old_files)
    if (
        not isinstance(snippet, dict)
        or set(snippet) != {"agent_profile", "mcp_config", "mcp_setup_commands", "scope"}
        or snippet["scope"] != "user"
    ):
        raise ClaudePlanError("The release merges config or has extra files or setup steps; update manually.")
    if snippet["mcp_config"] != {} or snippet["mcp_setup_commands"] != []:
        _existing_delegation(snippet, item["directory"])
    agent = snippet["agent_profile"]
    if (
        not isinstance(agent, dict)
        or set(agent) != {"path", "content"}
        or agent["path"] != f"~/.claude/agents/{item['local_name']}.md"
        or not isinstance(agent["content"], str)
    ):
        raise ClaudePlanError("The release changes the profile path or content type; update manually.")
    # write_install_snippet applies exactly this text transformation before
    # _write_file_checked atomically replaces the profile.
    from observal_cli.cmd_pull import _resolve_hook_paths

    raw = _resolve_hook_paths(agent["content"]).encode("utf-8")
    if len(raw) + file.stat().st_size > MAX_BYTES:
        raise ClaudePlanError("The profile exceeds the backup size limit; update manually.")
    return {file: raw}
