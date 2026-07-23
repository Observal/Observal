# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: Apache-2.0

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
from urllib.parse import urlsplit, urlunsplit

from loguru import logger as optic

from observal_cli.config import CONFIG_DIR

LOCKFILE_PATH = CONFIG_DIR / "lockfile.json"
_LOCKFILE_LOCK = CONFIG_DIR / "lockfile.lock"

# Schema version: bump when the structure changes in a breaking way
LOCK_VERSION = 2


# ---------------------------------------------------------------------------
# Read / Write primitives
# ---------------------------------------------------------------------------


def normalize_server_url(server_url: str) -> str:
    """Return the stable registry key for a server URL."""
    value = server_url.strip()
    parts = urlsplit(value if "://" in value else f"http://{value}")
    if not parts.hostname:
        raise ValueError("A configured server URL is required for lockfile operations")
    scheme = parts.scheme.lower()
    port = parts.port
    default_port = (scheme == "http" and port == 80) or (scheme == "https" and port == 443)
    host = parts.hostname.lower()
    netloc = host if port is None or default_port else f"{host}:{port}"
    return urlunsplit((scheme, netloc, parts.path.rstrip("/"), "", ""))


def current_registry_url() -> str:
    from observal_cli import config

    return normalize_server_url(str(config.load().get("server_url") or ""))


def migrate_lockfile_v1(server_url: str | None = None) -> bool:
    """Assign a version 1 lockfile to its previously configured registry."""
    if not LOCKFILE_PATH.exists():
        return False
    try:
        data = json.loads(LOCKFILE_PATH.read_text())
    except (json.JSONDecodeError, OSError) as exc:
        raise RuntimeError(f"Cannot read {LOCKFILE_PATH}: {exc}") from exc
    if not isinstance(data, dict):
        raise RuntimeError(f"Invalid lockfile structure in {LOCKFILE_PATH}")
    if data.get("lock_version") != 1:
        return False
    registry_url = normalize_server_url(server_url) if server_url else current_registry_url()
    write_lockfile(
        {
            "lock_version": LOCK_VERSION,
            "updated_at": datetime.now(UTC).isoformat(),
            "registries": {
                registry_url: {
                    "server_url": registry_url,
                    "harnesses": data.get("harnesses", {}),
                }
            },
        }
    )
    return True


def read_lockfile() -> dict:
    """Read the complete multi-registry lockfile, migrating version 1 once."""
    migrate_lockfile_v1()
    if not LOCKFILE_PATH.exists():
        return _empty_lockfile()
    try:
        data = json.loads(LOCKFILE_PATH.read_text())
    except (json.JSONDecodeError, OSError) as exc:
        raise RuntimeError(f"Cannot read {LOCKFILE_PATH}: {exc}") from exc
    if not isinstance(data, dict):
        raise RuntimeError(f"Invalid lockfile structure in {LOCKFILE_PATH}")
    if data.get("lock_version") != LOCK_VERSION or not isinstance(data.get("registries"), dict):
        raise RuntimeError(f"Unsupported lockfile version in {LOCKFILE_PATH}")
    return data


def write_lockfile(data: dict) -> None:
    """Write the complete lockfile atomically with file locking."""
    data["updated_at"] = datetime.now(UTC).isoformat()
    data["lock_version"] = LOCK_VERSION

    LOCKFILE_PATH.parent.mkdir(parents=True, exist_ok=True)
    lock_fd = None
    try:
        lock_fd = open(_LOCKFILE_LOCK, "w")  # noqa: SIM115
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
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


def read_registry_lockfile(*, create: bool = False) -> tuple[dict, dict]:
    """Return the complete lockfile and the current registry section."""
    data = read_lockfile()
    server_url = current_registry_url()
    registry = data["registries"].get(server_url)
    if registry is None:
        registry = {"server_url": server_url, "harnesses": {}}
        if create:
            data["registries"][server_url] = registry
    return data, registry


def _empty_lockfile() -> dict:
    return {
        "lock_version": LOCK_VERSION,
        "updated_at": datetime.now(UTC).isoformat(),
        "registries": {},
    }


def local_registry_name(
    harness: str,
    component_type: str,
    namespace: str,
    slug: str,
    *,
    scope: str = "user",
    directory: str | None = None,
) -> str:
    """Use the bare slug unless another installed namespace already uses it."""
    data = read_lockfile()
    current_url = current_registry_url()
    matching_entries: list[tuple[str, dict]] = []
    for registry_url, registry in data.get("registries", {}).items():
        section = registry.get("harnesses", {}).get(harness, {})
        entries = section.get("agents", []) if component_type == "agent" else section.get("standalone", [])
        for entry in entries:
            if component_type != "agent" and entry.get("type") != component_type:
                continue
            if scope == "project" and directory and entry.get("directory") != directory:
                continue
            matching_entries.append((registry_url, entry))

    collision = any(
        entry.get("slug") == slug and (entry.get("namespace") not in (None, namespace) or registry_url != current_url)
        for registry_url, entry in matching_entries
    )
    if not collision:
        return slug
    # Local names become harness config keys and on-disk names, where a dot reads
    # as a file extension — flattened the same way the registry host is below.
    candidate = f"{namespace.replace('.', '-')}-{slug}"
    if not any(entry.get("local_name") == candidate for _, entry in matching_entries):
        return candidate
    host = urlsplit(current_url).hostname or "registry"
    return f"{host.replace('.', '-')}-{candidate}"


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
    namespace: str | None = None,
    slug: str | None = None,
    local_name: str | None = None,
) -> None:
    """Add or update an agent entry in the lock file.

    Matches on (harness, agent_id, directory) for project-scoped or
    (harness, agent_id) for user-scoped.
    """
    optic.debug("upsert_agent: harness={}, name={}, version={}", harness, name, version)
    data, registry = read_registry_lockfile(create=True)
    harness_section = _ensure_harness(registry, harness)
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
    if namespace:
        entry["namespace"] = namespace
    if slug:
        entry["slug"] = slug
    if namespace and slug:
        entry["qualified_name"] = f"{namespace}/{slug}"
    if local_name:
        entry["local_name"] = local_name

    # Find existing entry to update
    existing_idx = _find_agent_idx(agents, agent_id, scope, directory)
    if existing_idx is not None:
        agents[existing_idx] = entry
    else:
        agents.append(entry)

    write_lockfile(data)


def remove_agent(harness: str, agent_id: str, directory: str | None = None) -> bool:
    """Remove an agent entry. Returns True if found and removed."""
    data, registry = read_registry_lockfile(create=True)
    harness_section = _ensure_harness(registry, harness)
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
    namespace: str | None = None,
    slug: str | None = None,
    local_name: str | None = None,
) -> None:
    """Add or update a standalone component (MCP, skill, hook, etc.) in the lock file."""
    optic.debug("upsert_standalone: harness={}, type={}, name={}", harness, component_type, name)
    data, registry = read_registry_lockfile(create=True)
    harness_section = _ensure_harness(registry, harness)
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
    if namespace:
        entry["namespace"] = namespace
    if slug:
        entry["slug"] = slug
    if namespace and slug:
        entry["qualified_name"] = f"{namespace}/{slug}"
    if local_name:
        entry["local_name"] = local_name

    # Find existing entry to update (match on type + id + scope + directory)
    existing_idx = _find_standalone_idx(standalone, component_type, component_id, scope, directory)
    if existing_idx is not None:
        standalone[existing_idx] = entry
    else:
        standalone.append(entry)

    write_lockfile(data)


def remove_standalone(harness: str, component_type: str, component_id: str, directory: str | None = None) -> bool:
    """Remove a standalone component entry. Returns True if found and removed."""
    data, registry = read_registry_lockfile(create=True)
    harness_section = _ensure_harness(registry, harness)
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
    _, registry = read_registry_lockfile()
    harness_section = registry.get("harnesses", {}).get(harness, {})
    for agent in harness_section.get("agents", []):
        if agent.get("directory") == directory:
            return agent
    return None


def get_agent_by_id(agent_id: str, harness: str | None = None) -> dict | None:
    """Find a lockfile agent by UUID, optionally scoped to one harness."""
    _, registry = read_registry_lockfile()
    for harness_name, harness_section in registry.get("harnesses", {}).items():
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
    _, registry = read_registry_lockfile()
    entries: list[dict] = []

    for harness_name, harness_section in registry.get("harnesses", {}).items():
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
    """Compute a short hash for the current registry section."""
    if not LOCKFILE_PATH.exists():
        return "0" * 16
    _, registry = read_registry_lockfile()
    content = json.dumps(registry, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(content).hexdigest()[:16]


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
