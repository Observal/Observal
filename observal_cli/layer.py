# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""IDE layer scanning and hash computation.

Scans IDE configuration directories to build a manifest of all files
that shape AI behavior (rules, agents, skills, MCP configs, hooks).
Computes a deterministic layer_hash from the manifest and manages
caching to avoid redundant file reads.

The layer_hash represents the FULL state the AI sees, not just what
Observal installed, but also user-created rules, custom agents, etc.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from loguru import logger as optic

from observal_cli.config import CONFIG_DIR

# Cache for file hashes by mtime (avoids re-reading unchanged files)
_FILE_HASH_CACHE_PATH = CONFIG_DIR / ".file_hash_cache.json"
_LOCAL_SNAPSHOT_PATH = CONFIG_DIR / "layer_snapshot.json"

# Maximum file size to include content (skip very large files)
MAX_FILE_SIZE = 512 * 1024  # 512KB


# ---------------------------------------------------------------------------
# Per-IDE file discovery configuration
# ---------------------------------------------------------------------------

# Maps IDE name → dict of scope → list of (base_dir, glob_patterns)
# base_dir is relative to home (~) for user scope, or project root for project scope
IDE_LAYER_CONFIGS: dict[str, dict[str, list[tuple[str, list[str]]]]] = {
    "claude-code": {
        "user": [
            (
                "~/.claude",
                [
                    "CLAUDE.md",
                    "agents/*.md",
                    "skills/*/SKILL.md",
                    "settings.json",
                ],
            ),
        ],
        "project": [
            (
                ".",
                [
                    ".claude/CLAUDE.md",
                    ".claude/agents/*.md",
                    ".claude/skills/*/SKILL.md",
                    ".claude/settings.local.json",
                    "CLAUDE.md",
                ],
            ),
        ],
    },
    "cursor": {
        "user": [
            (
                "~/.cursor",
                [
                    "rules/*.mdc",
                    "mcp.json",
                    "hooks.json",
                    "agents/*.md",
                    "skills/*/SKILL.md",
                ],
            ),
        ],
        "project": [
            (
                ".",
                [
                    ".cursor/rules/*.mdc",
                    ".cursor/mcp.json",
                    ".cursor/hooks.json",
                    ".cursor/agents/*.md",
                    ".cursor/skills/*/SKILL.md",
                ],
            ),
        ],
    },
    "kiro": {
        "user": [
            (
                "~/.kiro",
                [
                    "agents/*.json",
                    "skills/*/SKILL.md",
                    "settings/mcp.json",
                ],
            ),
        ],
        "project": [
            (
                ".",
                [
                    ".kiro/agents/*.json",
                    ".kiro/skills/*/SKILL.md",
                    ".kiro/settings/mcp.json",
                ],
            ),
        ],
    },
    "pi": {
        "user": [
            (
                "~/.pi/agent",
                [
                    "AGENTS.md",
                    "mcp.json",
                    "skills/*/SKILL.md",
                    "settings.json",
                ],
            ),
        ],
        "project": [
            (
                ".",
                [
                    "AGENTS.md",
                    ".pi/mcp.json",
                    ".pi/skills/*/SKILL.md",
                ],
            ),
        ],
    },
    "copilot": {
        "user": [
            (
                "~/.copilot",
                [
                    "instructions.md",
                    "hooks/*.json",
                ],
            ),
        ],
        "project": [
            (
                ".",
                [
                    ".github/copilot-instructions.md",
                    ".github/agents/*.agent.md",
                    ".vscode/mcp.json",
                    ".github/hooks/*.json",
                    ".github/skills/*/SKILL.md",
                    ".github/copilot/settings.json",
                ],
            ),
        ],
    },
    "opencode": {
        "user": [
            (
                "~/.config/opencode",
                [
                    "agents/*.md",
                    "opencode.json",
                    "skills/*/SKILL.md",
                    "plugins/*.ts",
                ],
            ),
        ],
        "project": [
            (
                ".",
                [
                    ".opencode/agents/*.md",
                    "opencode.json",
                    ".opencode/skills/*/SKILL.md",
                    ".opencode/plugins/*.ts",
                ],
            ),
        ],
    },
    "codex": {
        "user": [
            (
                "~/.codex",
                [
                    "config.toml",
                    "hooks.json",
                ],
            ),
        ],
        "project": [
            (
                ".",
                [
                    "AGENTS.md",
                    ".codex/config.toml",
                    ".codex/hooks.json",
                    ".agents/skills/*/SKILL.md",
                ],
            ),
        ],
    },
    "copilot-cli": {
        "user": [
            (
                "~/.copilot",
                [
                    "mcp-config.json",
                    "skills/*/SKILL.md",
                    "agents/*.agent.md",
                    "hooks/*.json",
                    "copilot-instructions.md",
                    "instructions/*.instructions.md",
                    "settings.json",
                ],
            ),
        ],
        "project": [
            (
                ".",
                [
                    ".github/copilot-instructions.md",
                    ".github/agents/*.agent.md",
                    ".mcp.json",
                    ".agents/skills/*/SKILL.md",
                    ".github/hooks/*.json",
                    ".github/copilot/settings.json",
                ],
            ),
        ],
    },
}


# ---------------------------------------------------------------------------
# File hash cache
# ---------------------------------------------------------------------------


def _load_hash_cache() -> dict[str, dict]:
    """Load {filepath: {mtime: float, hash: str}} from cache file."""
    if not _FILE_HASH_CACHE_PATH.exists():
        return {}
    try:
        return json.loads(_FILE_HASH_CACHE_PATH.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def _save_hash_cache(cache: dict[str, dict]) -> None:
    """Persist hash cache to disk."""
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        _FILE_HASH_CACHE_PATH.write_text(json.dumps(cache))
    except OSError:
        pass


def _hash_file(path: Path, cache: dict[str, dict]) -> tuple[str, int]:
    """Hash a file, using cache if mtime hasn't changed.

    Returns (sha256_hex, file_size).
    """
    try:
        stat = path.stat()
        size = stat.st_size
        mtime = stat.st_mtime
    except OSError:
        return "", 0

    key = str(path)
    cached = cache.get(key)
    if cached and cached.get("mtime") == mtime:
        return cached["hash"], size

    # Read and hash the file
    try:
        content = path.read_bytes()
        file_hash = hashlib.sha256(content).hexdigest()
        cache[key] = {"mtime": mtime, "hash": file_hash}
        return file_hash, size
    except OSError:
        return "", 0


# ---------------------------------------------------------------------------
# Layer manifest building
# ---------------------------------------------------------------------------


def _resolve_base_dir(base_dir: str) -> Path:
    """Resolve a base directory string to an absolute Path."""
    if base_dir.startswith("~"):
        return Path(base_dir).expanduser()
    return Path(base_dir)


def _discover_files(ide: str, project_dir: str | None = None) -> list[tuple[Path, str]]:
    """Discover all IDE config files for a given IDE.

    Returns list of (absolute_path, relative_display_path) tuples.
    Scans both user and project scopes.
    """
    config = IDE_LAYER_CONFIGS.get(ide, {})
    found: list[tuple[Path, str]] = []
    seen: set[str] = set()

    for scope in ("user", "project"):
        scope_configs = config.get(scope, [])
        for base_dir, patterns in scope_configs:
            if scope == "project" and not project_dir:
                continue

            resolved_base = Path(project_dir) if scope == "project" else _resolve_base_dir(base_dir)

            if not resolved_base.is_dir():
                continue

            for pattern in patterns:
                glob_base = resolved_base

                try:
                    for match in glob_base.glob(pattern):
                        if match.is_file() and match.stat().st_size <= MAX_FILE_SIZE:
                            abs_path = match.resolve()
                            # Safety: ensure file is under the base dir (no symlink escapes)
                            try:
                                abs_path.relative_to(glob_base.resolve())
                            except ValueError:
                                continue  # Symlink pointing outside base dir
                            # Create display path relative to scope root
                            try:
                                rel = match.relative_to(glob_base)
                                display = f"{scope}:{rel}"
                            except ValueError:
                                display = f"{scope}:{match.name}"

                            if display not in seen:
                                seen.add(display)
                                found.append((abs_path, display))
                except (OSError, PermissionError):
                    continue

    return found


def build_layer_manifest(
    ide: str,
    project_dir: str | None = None,
    include_content: bool = False,
) -> list[dict[str, Any]]:
    """Build the layer manifest for a given IDE.

    Args:
        ide: IDE identifier (e.g. 'claude-code', 'cursor')
        project_dir: Optional project directory for project-scope scanning
        include_content: If True, include full file content in manifest entries

    Returns:
        Sorted list of manifest entries: [{path, hash, size, source, content?}]
    """
    cache = _load_hash_cache()
    files = _discover_files(ide, project_dir)

    # Safety cap: max 200 files per manifest. If an IDE config dir
    # has more than this, something is wrong (e.g. node_modules matched).
    if len(files) > 200:
        optic.warning("layer scan found {} files, capping at 200", len(files))
        files = files[:200]

    manifest: list[dict[str, Any]] = []

    # Load lockfile to determine source (observal vs user)
    from observal_cli.lockfile import read_lockfile

    lockfile_data = read_lockfile()
    observal_files = _get_observal_managed_files(lockfile_data, ide, project_dir)

    for abs_path, display_path in files:
        file_hash, size = _hash_file(abs_path, cache)
        if not file_hash:
            continue

        entry: dict[str, Any] = {
            "path": display_path,
            "hash": f"sha256-{file_hash}",
            "size": size,
            "source": "observal" if display_path in observal_files else "user",
        }

        if include_content:
            try:
                content = abs_path.read_text(errors="replace")
                entry["content"] = content
            except OSError:
                entry["content"] = ""

        manifest.append(entry)

    # Save updated cache
    _save_hash_cache(cache)

    # Sort deterministically for consistent hashing
    manifest.sort(key=lambda e: e["path"])
    return manifest


def _get_observal_managed_files(lockfile_data: dict, ide: str, project_dir: str | None) -> set[str]:
    """Determine which display paths are managed by Observal from the lock file."""
    from observal_cli.ide import ensure_loaded, get_adapter

    ensure_loaded()
    try:
        adapter = get_adapter(ide)
    except KeyError:
        return set()
    return adapter.get_observal_managed_files(lockfile_data, project_dir)


# ---------------------------------------------------------------------------
# Multi-IDE layer hash computation
# ---------------------------------------------------------------------------


def _detect_active_ides() -> list[str]:
    """Detect which first-class IDEs are installed by checking their config directories."""
    from pathlib import Path

    # First-class IDEs (full session parsing, hooks, scanning, e2e tested).
    # copilot-cli is detected via ~/.copilot (its own home dir).
    # VS Code copilot has no reliable home-dir marker (uses .github/ + VS Code
    # settings); its project files are still scanned via project-scope globs
    # when another IDE triggers a scan.
    ide_dirs = {
        "claude-code": Path.home() / ".claude",
        "cursor": Path.home() / ".cursor",
        "kiro": Path.home() / ".kiro",
        "pi": Path.home() / ".pi" / "agent",
        "codex": Path.home() / ".codex",
        "copilot-cli": Path.home() / ".copilot",
        "opencode": Path.home() / ".config" / "opencode",
    }
    return [ide for ide, path in ide_dirs.items() if path.is_dir()]


def compute_layer_hash(ide: str | None = None, project_dir: str | None = None) -> str:
    """Compute the layer_hash for one or all IDEs.

    If ide is None, computes across ALL detected IDEs (combined hash).
    If ide is specified, computes for that IDE only.

    The hash is based on the sorted (ide:path, file_hash) pairs.
    Returns a 16-char hex string.
    """
    ides_to_scan = [ide] if ide else _detect_active_ides()

    all_entries: list[tuple[str, str]] = []
    for scan_ide in ides_to_scan:
        manifest = build_layer_manifest(scan_ide, project_dir, include_content=False)
        for entry in manifest:
            # Prefix with IDE name for uniqueness across IDEs
            all_entries.append((f"{scan_ide}/{entry['path']}", entry["hash"]))

    if not all_entries:
        return "0" * 16

    all_entries.sort()
    hash_input = json.dumps(all_entries, sort_keys=True)
    return hashlib.sha256(hash_input.encode()).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Local snapshot management
# ---------------------------------------------------------------------------


def get_last_uploaded_hash() -> str:
    """Read the layer_hash from the local snapshot (last synced state)."""
    try:
        if _LOCAL_SNAPSHOT_PATH.exists():
            data = json.loads(_LOCAL_SNAPSHOT_PATH.read_text())
            return data.get("hash", "")
    except (OSError, json.JSONDecodeError):
        pass
    return ""


def get_local_snapshot() -> dict | None:
    """Read the full local snapshot (mirror of what server has)."""
    try:
        if _LOCAL_SNAPSHOT_PATH.exists():
            return json.loads(_LOCAL_SNAPSHOT_PATH.read_text())
    except (OSError, json.JSONDecodeError):
        pass
    return None


def save_local_snapshot(snapshot: dict) -> None:
    """Save the snapshot locally (mirror of what was uploaded to server).

    Writes only to ~/.observal/layer_snapshot.json. Overwrites in place (no history).
    Validates payload size before writing to prevent disk flooding.
    """
    try:
        serialized = json.dumps(snapshot, indent=2)
        # Safety: cap at 5MB. Typical snapshot is 10-50KB.
        if len(serialized) > 5 * 1024 * 1024:
            optic.warning("layer snapshot too large ({}KB), skipping save", len(serialized) // 1024)
            return
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        _LOCAL_SNAPSHOT_PATH.write_text(serialized + "\n")
    except OSError:
        pass


def set_last_uploaded_hash(layer_hash: str) -> None:
    """Backward compat: called after upload. Now handled by save_local_snapshot."""
    # No-op: save_local_snapshot stores the hash inside the snapshot
    pass


def ensure_local_snapshot(ide: str | None = None, project_dir: str | None = None) -> str:
    """Generate the local snapshot if it doesn't exist or state changed. Returns the layer_hash.

    Scans ALL detected IDEs (not just one). Called after login, pull, or scan.
    Does NOT upload to server (that happens on session push).
    """
    current_hash = compute_layer_hash(ide=None, project_dir=project_dir)

    if not _LOCAL_SNAPSHOT_PATH.exists():
        payload = build_upload_payload(project_dir=project_dir)
        save_local_snapshot(payload)
        optic.debug("local snapshot generated (first time): hash={}", current_hash)
    elif needs_upload(current_hash):
        payload = build_upload_payload(project_dir=project_dir)
        save_local_snapshot(payload)
        optic.debug("local snapshot updated (state changed): hash={}", current_hash)

    return current_hash


def needs_upload(current_hash: str) -> bool:
    """Check if the current layer_hash differs from the local snapshot."""
    return current_hash != get_last_uploaded_hash()


def diff_local(ide: str | None = None, project_dir: str | None = None) -> dict | None:
    """Diff current layer state against the local snapshot.

    Returns None if no local snapshot exists or nothing changed.
    Returns {added: [...], removed: [...], modified: [...]} if changed.
    """
    local = get_local_snapshot()
    if not local:
        return None

    # Build current state across all first-class IDEs
    ides_to_scan = [ide] if ide else _detect_active_ides()

    current_files: dict[str, dict] = {}
    for scan_ide in ides_to_scan:
        manifest = build_layer_manifest(scan_ide, project_dir, include_content=False)
        for entry in manifest:
            key = f"{scan_ide}/{entry['path']}"
            current_files[key] = entry

    # Flatten local snapshot (structured by IDE)
    local_files: dict[str, dict] = {}
    local_ides = local.get("ides", {})
    if isinstance(local_ides, dict):
        for ide_name, files in local_ides.items():
            for f in files:
                key = f"{ide_name}/{f['path']}"
                local_files[key] = f
    # Backward compat: old flat "files" list
    elif "files" in local:
        local_files = {f["path"]: f for f in local.get("files", [])}

    local_paths = set(local_files.keys())
    current_paths = set(current_files.keys())

    added = [current_files[p] for p in current_paths - local_paths]
    removed = [local_files[p] for p in local_paths - current_paths]
    modified = []

    for path in local_paths & current_paths:
        if local_files[path]["hash"] != current_files[path]["hash"]:
            modified.append(
                {
                    "path": path,
                    "before_hash": local_files[path]["hash"],
                    "after_hash": current_files[path]["hash"],
                    "source": current_files[path].get("source", "user"),
                }
            )

    if not added and not removed and not modified:
        return None

    return {"added": added, "removed": removed, "modified": modified}


def build_upload_payload(ide: str | None = None, project_dir: str | None = None) -> dict:
    """Build the full layer snapshot payload for upload to the server.

    Scans all detected first-class IDEs. Structured by IDE.
    Includes file contents for server-side diffing and insight analysis.
    """
    ides_to_scan = [ide] if ide else _detect_active_ides()

    all_hash_entries: list[tuple[str, str]] = []
    ides_section: dict[str, list[dict[str, Any]]] = {}

    for scan_ide in ides_to_scan:
        manifest = build_layer_manifest(scan_ide, project_dir, include_content=True)
        ides_section[scan_ide] = manifest
        for entry in manifest:
            all_hash_entries.append((f"{scan_ide}/{entry['path']}", entry["hash"]))

    all_hash_entries.sort()
    layer_hash = hashlib.sha256(json.dumps(all_hash_entries, sort_keys=True).encode()).hexdigest()[:16]

    from observal_cli.lockfile import compute_lockfile_hash, read_lockfile

    # Embed exact version pins from lockfile
    lockfile_data = read_lockfile()
    pinned_versions = _extract_pinned_versions(lockfile_data)

    # Determine canonical vs dirty state
    drift_info = _compute_drift(lockfile_data, ides_section)

    return {
        "hash": layer_hash,
        "ides": ides_section,
        "lockfile_hash": compute_lockfile_hash(),
        "pinned_versions": pinned_versions,
        "drift": drift_info,
    }


def _extract_pinned_versions(lockfile_data: dict) -> dict:
    """Extract exact semver pins from the lockfile for embedding in snapshot.

    Returns:
    {
        "agents": [{"name": "x", "version": "1.2.0", "ide": "claude-code", "components": [...]}],
        "standalone": [{"type": "mcp", "name": "y", "version": "2.0.0", "ide": "cursor"}]
    }
    """
    agents: list[dict] = []
    standalone: list[dict] = []

    for ide_name, ide_section in lockfile_data.get("ides", {}).items():
        for agent in ide_section.get("agents", []):
            agents.append(
                {
                    "name": agent.get("name", ""),
                    "id": agent.get("id", ""),
                    "version": agent.get("version"),
                    "ide": ide_name,
                    "components": [
                        {"type": c.get("type"), "name": c.get("name"), "version": c.get("version")}
                        for c in agent.get("components", [])
                    ],
                }
            )
        for item in ide_section.get("standalone", []):
            standalone.append(
                {
                    "type": item.get("type", ""),
                    "name": item.get("name", ""),
                    "id": item.get("id", ""),
                    "version": item.get("version"),
                    "ide": ide_name,
                }
            )

    return {"agents": agents, "standalone": standalone}


def _compute_drift(lockfile_data: dict, ides_section: dict[str, list[dict]]) -> dict:
    """Compare lockfile integrity hashes against actual file hashes to detect drift.

    Returns:
    {
        "is_canonical": True/False,
        "drifted_files": [{"ide": "...", "path": "...", "expected": "...", "actual": "..."}]
    }
    """
    drifted: list[dict] = []

    for ide_name, ide_section in lockfile_data.get("ides", {}).items():
        # Build lookup of actual file hashes for this IDE
        actual_hashes: dict[str, str] = {}
        for f in ides_section.get(ide_name, []):
            actual_hashes[f["path"]] = f["hash"]

        # Check agent component integrity
        for agent in ide_section.get("agents", []):
            for comp in agent.get("components", []):
                integrity = comp.get("integrity")
                if not integrity:
                    continue
                # Match by component name to file path
                # Skills: user:skills/{name}/SKILL.md
                # Others: matched by name in the rules file
                comp_name = comp.get("name", "")
                comp_type = comp.get("type", "")
                expected_paths = _integrity_check_paths(ide_name, comp_type, comp_name)
                for path in expected_paths:
                    actual = actual_hashes.get(path)
                    if actual and actual != integrity:
                        drifted.append(
                            {
                                "ide": ide_name,
                                "path": path,
                                "component": comp_name,
                                "expected": integrity,
                                "actual": actual,
                            }
                        )

    return {
        "is_canonical": len(drifted) == 0,
        "drifted_files": drifted,
    }


def _integrity_check_paths(ide: str, comp_type: str, comp_name: str) -> list[str]:
    """Map a component type+name to expected file paths for integrity checking."""
    paths: list[str] = []
    if comp_type == "skill":
        paths.append(f"user:skills/{comp_name}/SKILL.md")
    # MCPs and hooks are in settings/mcp.json and hooks.json respectively,
    # not individually checkable via path.
    return paths
