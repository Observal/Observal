# SPDX-FileCopyrightText: 2026 Observal Contributors
# SPDX-License-Identifier: Apache-2.0

"""Non-mutating exact Pi file plan for the normal agent pull startup mode."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from observal_cli.shared.utils import sanitize_name

MAX_BYTES = 2 * 1024 * 1024


class InstallSkipError(ValueError):
    """The release needs explicit manual installation; no managed file was written."""


def _safe_path(raw: str, root: Path, directory: Path) -> Path:
    if not isinstance(raw, str) or not raw:
        raise InstallSkipError("The server returned an invalid Pi path.")
    if raw.startswith("~/"):
        candidate = Path.home() / raw[2:]
    elif raw.startswith("~"):
        raise InstallSkipError("The server returned an unsupported home path.")
    else:
        candidate = directory / raw
    if not candidate.is_absolute() or any(part.is_symlink() for part in (candidate, *candidate.parents)):
        raise InstallSkipError("A generated Pi path contains a symbolic link.")
    target = candidate.resolve()
    if not target.is_relative_to(root) or not target.is_file():
        raise InstallSkipError("The release changes the managed profile location or creates a file.")
    return target


def plan_pi_files(snippet: object, item: dict, old_files: dict[str, str]) -> dict[Path, bytes]:
    """Compute the complete *file* plan before any mutation.

    Do not call the manual pull writer: it merges files, invokes git/setup
    commands and can create paths before discovering a later conflict.
    """
    if not isinstance(snippet, dict) or set(snippet) - {"agent_profile", "skill_components", "mcp_config"}:
        raise InstallSkipError("The Pi release requires an unsupported config merge or setup action.")
    local_name = item.get("local_name")
    if not isinstance(local_name, str) or local_name in {"", ".", ".."} or Path(local_name).name != local_name:
        raise InstallSkipError("The installed Pi profile name is unknown.")
    root = (Path.home() / ".pi" / "agent" / "agents" / local_name).resolve()
    if not root.is_dir() or root.is_symlink():
        raise InstallSkipError("The managed Pi profile is unavailable.")
    directory = Path(item["directory"]).resolve()
    if not directory.is_dir():
        raise InstallSkipError("The original pull directory no longer exists.")
    profile = snippet.get("agent_profile")
    if not isinstance(profile, dict) or not isinstance(profile.get("content"), str):
        raise InstallSkipError("The Pi release has no directly writable agent profile.")
    profile_path = _safe_path(profile.get("path"), root, directory)
    if profile_path != root / "AGENTS.md":
        raise InstallSkipError("The Pi release changes its agent profile path.")
    planned: dict[Path, bytes] = {profile_path: profile["content"].encode()}
    mcp = snippet.get("mcp_config")
    if mcp is not None:
        if not isinstance(mcp, dict) or not isinstance(mcp.get("content"), dict):
            raise InstallSkipError("The Pi release has an unsupported MCP config.")
        mcp_path = _safe_path(mcp.get("path"), root, directory)
        if mcp_path != root / "mcp.json" or str(mcp_path) not in old_files:
            raise InstallSkipError("The Pi release changes or creates an MCP config.")
        try:
            previous_mcp = mcp_path.read_bytes()
            current_mcp = json.loads(previous_mcp)
        except (OSError, UnicodeError, ValueError) as error:
            raise InstallSkipError("The managed Pi MCP config cannot be checked.") from error
        if (
            hashlib.sha256(previous_mcp).hexdigest() != old_files[str(mcp_path)]
            or not isinstance(current_mcp, dict)
            or set(current_mcp) != {"mcpServers"}
            or not isinstance(current_mcp["mcpServers"], dict)
            or not isinstance(mcp["content"].get("mcpServers"), dict)
            or set(mcp["content"]) != {"mcpServers"}
            or set(current_mcp["mcpServers"]) != set(mcp["content"]["mcpServers"])
            or not current_mcp["mcpServers"]
        ):
            raise InstallSkipError("The Pi release changes MCP ownership or its file set; update manually.")
        # _write_file merges incoming entries into the existing JSON and then
        # atomically writes indent=2 plus a newline. Keep an exact plan for
        # that normal writer; an identical config remains a no-op at apply.
        if current_mcp == mcp["content"]:
            planned[mcp_path] = previous_mcp
        else:
            current_mcp["mcpServers"].update(mcp["content"]["mcpServers"])
            planned[mcp_path] = (json.dumps(current_mcp, indent=2) + "\n").encode("utf-8")
    skills = snippet.get("skill_components", [])
    if not isinstance(skills, list):
        raise InstallSkipError("The release has invalid skill components.")
    for component in skills:
        if not isinstance(component, dict) or component.get("git_url"):
            raise InstallSkipError("Git skills require a manual pull.")
        content = component.get("skill_md_content")
        name = component.get("name")
        if not isinstance(content, str) or not content or not isinstance(name, str):
            raise InstallSkipError("The release requires an unsupported skill source.")
        target = _safe_path(component.get("path"), root, directory)
        if target != root / "skills" / sanitize_name(name) / "SKILL.md" or target in planned:
            raise InstallSkipError("The release changes or duplicates a managed skill path.")
        planned[target] = content.encode()
        script = component.get("script_content")
        filename = component.get("script_filename")
        if script is not None or filename is not None:
            if (
                not isinstance(script, str)
                or not script
                or not isinstance(filename, str)
                or filename in {"", ".", ".."}
                or Path(filename).name != filename
            ):
                raise InstallSkipError("The skill's registry script is incomplete or unsafe.")
            script_path = _safe_path(str(target.parent / "scripts" / filename), root, directory)
            if script_path in planned:
                raise InstallSkipError("The release duplicates a managed script path.")
            planned[script_path] = script.encode()
    if set(map(str, planned)) != set(old_files):
        raise InstallSkipError("The target file plan differs from the manual pull's ownership baseline.")
    if sum(path.stat().st_size + len(data) for path, data in planned.items()) > MAX_BYTES:
        raise InstallSkipError("The automatic installation exceeds its file-size limit.")
    return planned
