# SPDX-License-Identifier: Apache-2.0

"""Non-mutating Pi file-plan check shared by the normal agent pull startup mode."""

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
            or set(current_mcp["mcpServers"]) != {"observal-agents"}
            or current_mcp != mcp["content"]
        ):
            raise InstallSkipError("The Pi release changes an MCP config; update manually.")
        # The normal installer would merge and replace this file even though
        # its content is identical. Keep it in the verified ownership set but
        # remove it from the snippet before invoking the shared writer.
        planned[mcp_path] = previous_mcp
    skills = snippet.get("skill_components", [])
    if not isinstance(skills, list):
        raise InstallSkipError("The release has invalid skill components.")
    for component in skills:
        if not isinstance(component, dict) or component.get("git_url") or component.get("script_content"):
            raise InstallSkipError("Git or executable skill installs require a manual pull.")
        content = component.get("skill_md_content")
        name = component.get("name")
        if not isinstance(content, str) or not content or not isinstance(name, str):
            raise InstallSkipError("The release requires an unsupported skill source.")
        target = _safe_path(component.get("path"), root, directory)
        if target != root / "skills" / sanitize_name(name) / "SKILL.md" or target in planned:
            raise InstallSkipError("The release changes or duplicates a managed skill path.")
        planned[target] = content.encode()
    if set(map(str, planned)) != set(old_files):
        raise InstallSkipError("The target file plan differs from the manual pull's ownership baseline.")
    if sum(path.stat().st_size + len(data) for path, data in planned.items()) > MAX_BYTES:
        raise InstallSkipError("The automatic installation exceeds its file-size limit.")
    return planned
