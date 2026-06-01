# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Shared utility functions used across multiple CLI modules.

Single source of truth - helpers that were duplicated across cmd_scan.py,
cmd_doctor.py, cmd_skill.py, and claude_code_hooks_spec.py live here instead.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

# ---------------------------------------------------------------------------
# Name sanitization
# ---------------------------------------------------------------------------

_SAFE_CLI_NAME = re.compile(r"^[a-z0-9_-]+$")


def sanitize_name(name: str) -> str:
    """Normalise an arbitrary string to a safe lowercase slug.

    Lowercases, strips whitespace, replaces unsafe characters with hyphens,
    collapses consecutive hyphens, and strips leading/trailing hyphens.
    Returns "skill" as a last-resort fallback for an all-stripped input.

    Raises TypeError if *name* is not a str.
    """
    if not isinstance(name, str):
        raise TypeError(f"sanitize_name expects str, got {type(name).__name__!r}")
    name = name.lower().strip()
    name = re.sub(r"[^a-z0-9_-]", "-", name)
    name = re.sub(r"-{2,}", "-", name).strip("-")
    return name or "skill"


# ---------------------------------------------------------------------------
# JSON / JSONC loading
# ---------------------------------------------------------------------------


def load_jsonc(path: Path) -> dict:
    """Load a JSON file that may contain // line comments (JSONC).

    Raises TypeError if *path* is not a Path.
    """
    if not isinstance(path, Path):
        raise TypeError(f"load_jsonc expects Path, got {type(path).__name__!r}")
    text = path.read_text()
    stripped = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("//"))
    return json.loads(stripped)


# ---------------------------------------------------------------------------
# MCP server extraction
# ---------------------------------------------------------------------------

# IDE-specific top-level keys for MCP server maps.
_MCP_KEY_BY_IDE: dict[str, str] = {
    "copilot": "servers",
    "opencode": "mcp",
}


def resolve_wsl_windows_home() -> Path | None:
    """Return the Windows user home as a WSL path, or None if not on WSL.

    Tries cmd.exe first (most reliable), then falls back to scanning /mnt/c/Users/
    for the directory that matches the current Linux username.
    """
    import subprocess

    # Method 1: cmd.exe + wslpath (works when cmd.exe is available)
    try:
        win_user = subprocess.check_output(
            ["cmd.exe", "/c", "echo %USERPROFILE%"], text=True, stderr=subprocess.DEVNULL
        ).strip()
        wsl_path = subprocess.check_output(["wslpath", win_user], text=True, stderr=subprocess.DEVNULL).strip()
        p = Path(wsl_path)
        if p.is_dir():
            return p
    except Exception:
        pass

    # Method 2: scan /mnt/c/Users/ for a directory matching the Linux username
    try:
        import os

        linux_user = os.environ.get("USER") or os.environ.get("LOGNAME") or ""
        mnt_users = Path("/mnt/c/Users")
        if mnt_users.is_dir():
            # Prefer exact username match, then case-insensitive match
            for candidate in mnt_users.iterdir():
                if candidate.is_dir() and candidate.name.lower() == linux_user.lower():
                    return candidate
            # Last resort: any non-system directory
            for candidate in mnt_users.iterdir():
                if candidate.is_dir() and candidate.name not in ("Public", "Default", "All Users", "Default User"):
                    return candidate
    except Exception:
        pass

    return None


def resolve_antigravity_dir(home: Path | None = None) -> Path | None:
    """Return the antigravity-cli config dir, with WSL Windows path fallback."""
    h = home or Path.home()
    ag_dir = h / ".gemini" / "antigravity-cli"
    if ag_dir.exists():
        return ag_dir
    win_home = resolve_wsl_windows_home()
    if win_home:
        candidate = win_home / ".gemini" / "antigravity-cli"
        if candidate.exists():
            return candidate
    return None


def resolve_antigravity_config_dir(home: Path | None = None) -> Path | None:
    """Return ~/.gemini/config/ with WSL Windows path fallback.

    This is where agy stores hooks.json and mcp_config.json (global scope).
    """
    h = home or Path.home()
    config_dir = h / ".gemini" / "config"
    if config_dir.exists():
        return config_dir
    win_home = resolve_wsl_windows_home()
    if win_home:
        candidate = win_home / ".gemini" / "config"
        if candidate.exists():
            return candidate
    return None


def extract_mcp_servers(config: dict, ide: str = "") -> dict:
    """Extract the MCP server map from an IDE config dict.

    Resolves IDE-specific key paths:
    - ``servers``    - VS Code, Copilot
    - ``mcp``        - OpenCode (flat server map under ``mcp`` key)
    - ``mcp.servers``- Codex (nested under ``mcp`` → ``servers``)
    - ``mcpServers`` - all other IDEs (default)

    Falls back to scanning for server-shaped top-level values when the
    expected key is absent.

    Raises TypeError if *config* is not a dict.
    """
    if not isinstance(config, dict):
        raise TypeError(f"extract_mcp_servers expects dict, got {type(config).__name__!r}")

    # Codex: nested mcp.servers
    if ide == "codex":
        mcp_block = config.get("mcp", {})
        if isinstance(mcp_block, dict) and "servers" in mcp_block:
            return mcp_block["servers"]

    # IDE-specific top-level key
    ide_key = _MCP_KEY_BY_IDE.get(ide)
    if ide_key and ide_key in config:
        return config[ide_key]

    # Default: mcpServers
    if "mcpServers" in config:
        return config["mcpServers"]

    # Fallback: scan for server-shaped values
    servers = {}
    for key, val in config.items():
        if isinstance(val, dict) and ("command" in val or "url" in val or "type" in val):
            servers[key] = val
    return servers


# ---------------------------------------------------------------------------
# Shim detection
# ---------------------------------------------------------------------------


def is_already_shimmed(entry: dict) -> bool:
    """Return True if an MCP server entry is already wrapped with observal-shim.

    Raises TypeError if *entry* is not a dict.
    """
    if not isinstance(entry, dict):
        raise TypeError(f"is_already_shimmed expects dict, got {type(entry).__name__!r}")
    cmd = entry.get("command", "")
    args = entry.get("args", [])
    if cmd == "observal-shim" or "observal-shim" in cmd:
        return True
    return bool(any("observal-shim" in str(a) for a in args))


# ---------------------------------------------------------------------------
# Hook marker detection
# ---------------------------------------------------------------------------

# Metadata key injected into every Observal-managed matcher group.
OBSERVAL_METADATA_KEY = "_observal"

# Comprehensive set of substrings that identify any Observal-injected hook.
# Used for both scan detection and idempotent cleanup.
_OBSERVAL_HOOK_MARKERS = (
    # Legacy marker names
    "observal-hook",
    "observal-stop-hook",
    # Current session push modules
    "observal_cli.hooks.session_push",
    "observal_cli.hooks.kiro_session_push",
    "observal_cli.hooks.cursor_session_push",
    "observal_cli.hooks.antigravity_session_push",
    # Legacy hook modules
    "observal_cli.hooks.kiro_hook",
    "observal_cli.hooks.kiro_stop_hook",
    "observal_cli.hooks.copilot_cli_hook",
    "observal_cli.hooks.copilot_cli_stop_hook",
    "observal_cli.hooks.buffer_event",
    "observal_cli.hooks.flush_buffer",
    # Catch-all for any observal_cli hook
    "observal_cli",
    # API endpoints
    "/api/v1/telemetry/hooks",
    # Legacy endpoint (removed, still detected for cleanup)
    "/api/v1/otel/hooks",
)


def is_observal_hook_entry(entry: dict) -> bool:
    """Return True if a single hook handler dict belongs to Observal.

    Raises TypeError if *entry* is not a dict.
    """
    if not isinstance(entry, dict):
        raise TypeError(f"is_observal_hook_entry expects dict, got {type(entry).__name__!r}")
    cmd = entry.get("command", "")
    url = entry.get("url", "")
    return any(m in cmd or m in url for m in _OBSERVAL_HOOK_MARKERS)


def is_observal_matcher_group(group: dict) -> bool:
    """Return True if a matcher group is Observal-managed.

    Raises TypeError if *group* is not a dict.
    """
    if not isinstance(group, dict):
        raise TypeError(f"is_observal_matcher_group expects dict, got {type(group).__name__!r}")
    if OBSERVAL_METADATA_KEY in group:
        return True
    return any(is_observal_hook_entry(h) for h in group.get("hooks", []))


# ---------------------------------------------------------------------------
# Frontmatter / markdown helpers (used by scanning adapters)
# ---------------------------------------------------------------------------


def parse_frontmatter_field(content: str, field: str) -> str | None:
    """Extract a field from YAML frontmatter (--- delimited)."""
    match = re.match(r"^---\s*\n(.*?)\n---", content, re.DOTALL)
    if not match:
        return None
    for line in match.group(1).splitlines():
        if line.startswith(f"{field}:"):
            val = line[len(field) + 1 :].strip().strip('"').strip("'")
            return val
    return None


def extract_body(content: str) -> str:
    """Extract everything after YAML frontmatter."""
    match = re.match(r"^---\s*\n.*?\n---\s*\n?", content, re.DOTALL)
    if match:
        return content[match.end() :]
    return content


def first_content_line(content: str) -> str:
    """Get first non-empty, non-heading content line after frontmatter."""
    in_frontmatter = False
    past_frontmatter = False
    for line in content.splitlines():
        stripped = line.strip()
        if stripped == "---":
            if not in_frontmatter:
                in_frontmatter = True
                continue
            else:
                past_frontmatter = True
                continue
        if not past_frontmatter and in_frontmatter:
            continue
        if past_frontmatter and stripped and not stripped.startswith("#"):
            return stripped[:200]
    return ""
