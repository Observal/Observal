# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Lock file management for Observal CLI.

Manages ~/.observal/lockfile.json, the canonical record of all agents,
MCPs, skills, hooks, and sandboxes installed via Observal, organized by harness.

The lock file is:
- Written on `observal pull`, `observal mcp install`, `observal skill install`
- Read on session push to resolve agent attribution and compute layer_hash
- Read by `observal outdated` to compare pinned versions against registry latest
"""

from __future__ import annotations

import fcntl
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from loguru import logger as optic

from observal_cli.config import CONFIG_DIR

LOCKFILE_PATH = CONFIG_DIR / "lockfile.json"
_LOCKFILE_LOCK = CONFIG_DIR / "lockfile.lock"

# Schema version: bump when the structure changes in a breaking way
LOCK_VERSION = 1


# ---------------------------------------------------------------------------
# Read / Write primitives
# ---------------------------------------------------------------------------


def read_lockfile() -> dict:
    """Read and return the lock file contents, or an empty structure if missing/corrupt."""
    if not LOCKFILE_PATH.exists():
        return _empty_lockfile()
    try:
        data = json.loads(LOCKFILE_PATH.read_text())
        if not isinstance(data, dict) or data.get("lock_version") != LOCK_VERSION:
            optic.warning("lockfile version mismatch or corrupt, returning empty")
            return _empty_lockfile()
        return data
    except (json.JSONDecodeError, OSError) as e:
        optic.warning("failed to read lockfile: {}", e)
        return _empty_lockfile()


def write_lockfile(data: dict) -> None:
    """Write the lock file atomically with file locking (prevents concurrent overwrites)."""
    data["updated_at"] = datetime.now(UTC).isoformat()
    data["lock_version"] = LOCK_VERSION

    CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    # Acquire exclusive lock to prevent concurrent read-modify-write races
    lock_fd = None
    try:
        lock_fd = open(_LOCKFILE_LOCK, "w")  # noqa: SIM115
        fcntl.flock(lock_fd, fcntl.LOCK_EX)

        # Atomic write: write to temp file then rename
        tmp_path = LOCKFILE_PATH.with_suffix(".tmp")
        try:
            tmp_path.write_text(json.dumps(data, indent=2) + "\n")
            tmp_path.replace(LOCKFILE_PATH)
        finally:
            if tmp_path.exists():
                tmp_path.unlink(missing_ok=True)
    finally:
        if lock_fd:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
            lock_fd.close()

    optic.debug("lockfile written: {}", LOCKFILE_PATH)


def _empty_lockfile() -> dict:
    """Return an empty lock file structure."""
    return {
        "lock_version": LOCK_VERSION,
        "updated_at": datetime.now(UTC).isoformat(),
        "harnesses": {},
    }


def _ensure_harness(data: dict, harness: str) -> dict:
    """Ensure the harness section exists in the lock file data."""
    harnesses = data.setdefault("harnesses", {})
    if harness not in harnesses:
        harnesses[harness] = {"agents": [], "standalone": []}
    else:
        # Ensure both keys exist
        harnesses[harness].setdefault("agents", [])
        harnesses[harness].setdefault("standalone", [])
    return harnesses[harness]


# ---------------------------------------------------------------------------
# Agent operations
# ---------------------------------------------------------------------------


def upsert_agent(
    harness: str,
    *,
    name: str,
    agent_id: str,
    version: str | None,
    scope: str = "project",
    directory: str | None = None,
    components: list[dict] | None = None,
) -> None:
    """Add or update an agent entry in the lock file.

    Matches on (ide, agent_id, directory) for project-scoped or
    (ide, agent_id) for user-scoped.
    """
    optic.debug("upsert_agent: ide={}, name={}, version={}", harness, name, version)
    data = read_lockfile()
    harness_section = _ensure_harness(data, harness)
    agents = harness_section["agents"]

    entry = {
        "name": name,
        "id": agent_id,
        "version": version,
        "pulled_at": datetime.now(UTC).isoformat(),
        "scope": scope,
    }
    if directory:
        entry["directory"] = directory
    if components:
        entry["components"] = components

    # Find existing entry to update
    existing_idx = _find_agent_idx(agents, agent_id, scope, directory)
    if existing_idx is not None:
        agents[existing_idx] = entry
    else:
        agents.append(entry)

    write_lockfile(data)


def remove_agent(harness: str, agent_id: str, directory: str | None = None) -> bool:
    """Remove an agent entry. Returns True if found and removed."""
    data = read_lockfile()
    harness_section = _ensure_harness(data, harness)
    agents = harness_section["agents"]

    for i, agent in enumerate(agents):
        if agent.get("id") == agent_id:
            if directory and agent.get("directory") != directory:
                continue
            agents.pop(i)
            write_lockfile(data)
            return True
    return False


def _find_agent_idx(agents: list[dict], agent_id: str, scope: str, directory: str | None) -> int | None:
    """Find index of matching agent entry."""
    for i, agent in enumerate(agents):
        if agent.get("id") == agent_id:
            if scope == "project" and directory:
                if agent.get("directory") == directory:
                    return i
            else:
                # User-scoped: match on id alone
                if agent.get("scope") != "project":
                    return i
    return None


# ---------------------------------------------------------------------------
# Standalone component operations
# ---------------------------------------------------------------------------


def upsert_standalone(
    harness: str,
    *,
    component_type: str,
    name: str,
    component_id: str,
    version: str | None,
    scope: str = "user",
    directory: str | None = None,
    integrity: str | None = None,
) -> None:
    """Add or update a standalone component (MCP, skill, hook, etc.) in the lock file."""
    optic.debug("upsert_standalone: ide={}, type={}, name={}", harness, component_type, name)
    data = read_lockfile()
    harness_section = _ensure_harness(data, harness)
    standalone = harness_section["standalone"]

    entry: dict[str, Any] = {
        "type": component_type,
        "name": name,
        "id": component_id,
        "version": version,
        "scope": scope,
        "installed_at": datetime.now(UTC).isoformat(),
    }
    if directory:
        entry["directory"] = directory
    if integrity:
        entry["integrity"] = integrity

    # Find existing entry to update (match on type + id + scope + directory)
    existing_idx = _find_standalone_idx(standalone, component_type, component_id, scope, directory)
    if existing_idx is not None:
        standalone[existing_idx] = entry
    else:
        standalone.append(entry)

    write_lockfile(data)


def remove_standalone(harness: str, component_type: str, component_id: str, directory: str | None = None) -> bool:
    """Remove a standalone component entry. Returns True if found and removed."""
    data = read_lockfile()
    harness_section = _ensure_harness(data, harness)
    standalone = harness_section["standalone"]

    for i, item in enumerate(standalone):
        if item.get("type") == component_type and item.get("id") == component_id:
            if directory and item.get("directory") != directory:
                continue
            standalone.pop(i)
            write_lockfile(data)
            return True
    return False


def _find_standalone_idx(
    standalone: list[dict],
    component_type: str,
    component_id: str,
    scope: str,
    directory: str | None,
) -> int | None:
    """Find index of matching standalone entry."""
    for i, item in enumerate(standalone):
        if item.get("type") == component_type and item.get("id") == component_id:
            if scope == "project" and directory:
                if item.get("directory") == directory:
                    return i
            else:
                if item.get("scope") != "project":
                    return i
    return None


# ---------------------------------------------------------------------------
# Query helpers
# ---------------------------------------------------------------------------


def get_agent_for_directory(harness: str, directory: str) -> dict | None:
    """Find the agent installed for a given harness + project directory.

    Used by session push to attribute sessions to agents.
    """
    data = read_lockfile()
    harness_section = data.get("harnesses", {}).get(harness, {})
    for agent in harness_section.get("agents", []):
        if agent.get("directory") == directory:
            return agent
    return None


def get_agent_by_id(agent_id: str, harness: str | None = None) -> dict | None:
    """Find a lockfile agent by UUID, optionally scoped to one harness."""
    data = read_lockfile()
    for harness_name, harness_section in data.get("harnesses", {}).items():
        if harness and harness_name != harness:
            continue
        for agent in harness_section.get("agents", []):
            if agent.get("id") == agent_id:
                return agent
    return None


def get_all_entries(harness: str | None = None) -> list[dict]:
    """Get all lock file entries, optionally filtered by harness.

    Returns a flat list of entries with 'harness' and 'entry_type' fields added.
    Used by `observal outdated`.
    """
    data = read_lockfile()
    entries: list[dict] = []

    for harness_name, harness_section in data.get("harnesses", {}).items():
        if harness and harness_name != harness:
            continue
        for agent in harness_section.get("agents", []):
            entries.append({**agent, "harness": harness_name, "entry_type": "agent"})
        for item in harness_section.get("standalone", []):
            entries.append({**item, "harness": harness_name, "entry_type": "standalone"})

    return entries


# ---------------------------------------------------------------------------
# Hash computation
# ---------------------------------------------------------------------------


def compute_lockfile_hash() -> str:
    """Compute a short hash of the lock file contents.

    Returns a 16-char hex string. Used as part of layer_hash computation
    and embedded in layer snapshots.
    """
    if not LOCKFILE_PATH.exists():
        return "0" * 16
    try:
        content = LOCKFILE_PATH.read_bytes()
        return hashlib.sha256(content).hexdigest()[:16]
    except OSError:
        return "0" * 16


def compute_integrity(content: str) -> str:
    """Compute sha256 integrity hash for a file's content."""
    return f"sha256-{hashlib.sha256(content.encode()).hexdigest()}"


# ---------------------------------------------------------------------------
# Migration from .observal/agent markers
# ---------------------------------------------------------------------------


def migrate_agent_markers() -> int:
    """Migrate existing .observal/agent markers to the lock file.

    Scans common project directories for .observal/agent files,
    reads them, and creates lock file entries. Returns count of migrated entries.

    This is called once on first CLI run when lockfile.json doesn't exist.
    """
    if LOCKFILE_PATH.exists():
        return 0  # Already migrated

    optic.info("migrating .observal/agent markers to lockfile.json")
    migrated = 0
    markers_found: list[tuple[Path, dict]] = []

    # Scan sync_state.json for known project directories
    state_file = CONFIG_DIR / "sync_state.json"
    if state_file.exists():
        try:
            json.loads(state_file.read_text())
            # sync_state keys are session IDs, but we can look for project markers
            # in common directories. Better approach: scan home for .observal/agent files.
        except Exception:
            pass

    # Scan common locations for .observal/agent files
    home = Path.home()
    search_roots = []

    # Check common code directories
    for candidate in ["code", "projects", "dev", "workspace", "src", "repos"]:
        root = home / candidate
        if root.is_dir():
            search_roots.append(root)

    # Also check CWD and its parents
    cwd = Path.cwd()
    if cwd != home:
        search_roots.append(cwd)
        if cwd.parent != home and cwd.parent.exists():
            search_roots.append(cwd.parent)

    for root in search_roots:
        try:
            # Look up to 3 levels deep for .observal/agent files
            for marker in root.glob("**/.observal/agent"):
                # Limit depth
                rel = marker.relative_to(root)
                if len(rel.parts) > 5:  # .observal/agent = 2 parts + up to 3 dir levels
                    continue
                try:
                    marker_data = json.loads(marker.read_text())
                    markers_found.append((marker.parent.parent, marker_data))
                except (json.JSONDecodeError, OSError):
                    continue
        except (OSError, PermissionError):
            continue

    if not markers_found:
        # Create empty lockfile so migration doesn't re-run
        write_lockfile(_empty_lockfile())
        return 0

    data = _empty_lockfile()
    seen: set[str] = set()  # Deduplicate by (agent_id, directory)

    for project_dir, marker_data in markers_found:
        agent_id = marker_data.get("agent_id")
        if not agent_id:
            continue

        directory = str(project_dir.resolve())
        key = f"{agent_id}:{directory}"
        if key in seen:
            continue
        seen.add(key)

        # We don't know which harness was used, default to claude-code
        # (the marker was primarily written by claude-code hooks)
        harness = "claude-code"
        harness_section = _ensure_harness(data, harness)

        harness_section["agents"].append(
            {
                "name": agent_id,  # Old markers stored ID as name too
                "id": agent_id,
                "version": marker_data.get("agent_version"),
                "pulled_at": marker_data.get("pulled_at", datetime.now(UTC).isoformat()),
                "scope": "project",
                "directory": directory,
                "components": [],
            }
        )
        migrated += 1

    write_lockfile(data)

    # Delete old marker files after successful migration
    for project_dir, _ in markers_found:
        marker_path = project_dir / ".observal" / "agent"
        try:
            marker_path.unlink(missing_ok=True)
            # Remove .observal dir if empty
            observal_dir = project_dir / ".observal"
            if observal_dir.is_dir() and not any(observal_dir.iterdir()):
                observal_dir.rmdir()
        except OSError:
            pass

    optic.info("migrated {} agent markers to lockfile.json", migrated)
    return migrated
