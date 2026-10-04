# SPDX-FileCopyrightText: 2026 Observal Contributors
# SPDX-License-Identifier: Apache-2.0

"""Entry-level ownership of credential-free Claude Code user-scope MCP servers.

Claude Code rewrites ``~/.claude.json`` while it runs, so Observal never edits
that file. It drives Claude's own CLI (``claude mcp add/remove -s user``) and
owns only the single entry it created, proven by a private record of the exact
entry it saw afterward. A pasted or edited entry is never adopted or replaced.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import time
from pathlib import Path

from observal_cli import auto_update_policy, client, config, lockfile

RECORD_DIR = config.CONFIG_DIR / "managed-claude-mcp"
RECOVERY_FILE = "claude-mcp.json"
CLI_TIMEOUT = 20


class ClaudeMcpError(ValueError):
    """The Claude Code MCP entry needs explicit manual inspection."""


def config_path() -> Path:
    custom = os.environ.get("CLAUDE_CONFIG_DIR")
    home = Path.home()
    if custom and Path(custom).expanduser() != home / ".claude":
        raise ClaudeMcpError("Claude Code uses a different config directory; update manually.")
    return home / ".claude.json"


def normalize(entry: object) -> dict:
    """Comparable shape of a stdio entry; anything else is not ours to manage."""
    if (
        not isinstance(entry, dict)
        or entry.get("type") not in (None, "stdio")
        or not isinstance(entry.get("command"), str)
        or not entry["command"]
        or not isinstance(entry.get("args", []), list)
        or any(not isinstance(arg, str) for arg in entry.get("args", []))
        or entry.get("env") not in (None, {})
        or set(entry) - {"type", "command", "args", "env"}
    ):
        raise ClaudeMcpError("The Claude Code MCP entry is not a plain credential-free stdio server.")
    return {"command": entry["command"], "args": list(entry.get("args", []))}


def read_entry(name: str) -> dict | None:
    path = config_path()
    if not path.exists():
        return None
    if path.is_symlink() or path.stat().st_size > 8 * 1024 * 1024:
        raise ClaudeMcpError("The Claude Code config is unsafe to read; update manually.")
    servers = json.loads(path.read_text(encoding="utf-8")).get("mcpServers", {})
    if not isinstance(servers, dict):
        raise ClaudeMcpError("The Claude Code user MCP section is malformed.")
    entry = servers.get(name)
    return None if entry is None else normalize(entry)


def _record_path(registry: str, component_id: str) -> Path:
    key = hashlib.sha256(f"{lockfile.normalize_server_url(registry)}\0{component_id}".encode()).hexdigest()
    return RECORD_DIR / f"{key}.json"


def load_record(registry: str, component_id: str) -> dict | None:
    path = _record_path(registry, component_id)
    if not path.exists():
        return None
    if path.is_symlink() or path.stat().st_mode & 0o077:
        raise ClaudeMcpError("The managed MCP record is not private; inspect it manually.")
    record = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(record, dict) or not isinstance(record.get("name"), str):
        raise ClaudeMcpError("The managed MCP record is malformed.")
    normalize({"command": record["entry"]["command"], "args": record["entry"]["args"]})
    return record


def _save_record(registry: str, component_id: str, name: str, entry: dict) -> None:
    RECORD_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = _record_path(registry, component_id)
    body = json.dumps({"schema": 1, "name": name, "entry": entry}).encode()
    temporary = path.with_suffix(".tmp")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as handle:
        handle.write(body)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def _run(*argv: str) -> None:
    claude = shutil.which("claude")
    if not claude:
        raise ClaudeMcpError("The `claude` command is not on PATH; install the MCP manually.")
    done = subprocess.run(
        [claude, "mcp", *argv],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=CLI_TIMEOUT,
        check=False,
    )
    if done.returncode != 0:
        raise ClaudeMcpError("Claude Code refused the MCP change; inspect it manually.")


def _add(name: str, entry: dict) -> None:
    _run("add", "-s", "user", name, "--", entry["command"], *entry["args"])


def parse_snippet(snippet: object, local_name: str) -> dict:
    """The exact `claude mcp add` the server generated, no shell involved."""
    command = snippet.get("command") if isinstance(snippet, dict) else None
    if (
        not isinstance(snippet, dict)
        or set(snippet) != {"command", "type"}
        or snippet["type"] != "shell_command"
        or not isinstance(command, list)
        or len(command) < 6
        or command[:5] != ["claude", "mcp", "add", local_name, "--"]
        or any(not isinstance(part, str) or not part for part in command)
    ):
        raise ClaudeMcpError("No exact credential-free stdio Claude Code MCP command was returned.")
    return {"command": command[5], "args": command[6:]}


def install(
    *,
    registry: str,
    component_id: str,
    name: str,
    namespace: str | None,
    slug: str | None,
    local_name: str,
    version: str,
    version_id: str | None,
    digest_value: str | None,
    requested_version: str | None,
    entry: dict,
) -> str:
    """Create (explicit) or replace (explicit/automatic) exactly the owned entry."""
    record = load_record(registry, component_id)
    current = read_entry(local_name)
    automatic = os.environ.get("OBSERVAL_AUTO_UPDATE_INSTALL") == "1"
    if record is None:
        if automatic:
            raise ClaudeMcpError("This MCP has no Observal ownership record; update manually.")
        if current is not None:
            raise ClaudeMcpError("A Claude Code MCP with this name already exists; Observal will not adopt it.")
        _add(local_name, entry)
    else:
        if record["name"] != local_name or current != record["entry"]:
            raise ClaudeMcpError("The Claude Code MCP entry changed since Observal installed it; update manually.")
        if automatic:
            _guard_automatic(registry, component_id)
        if current != entry:
            if automatic:
                _save_recovery(
                    Path(os.environ["OBSERVAL_AUTO_UPDATE_RECOVERY_DIR"]), local_name, record["entry"], entry
                )
            _run("remove", "-s", "user", local_name)
            try:
                _add(local_name, entry)
            except (ClaudeMcpError, subprocess.SubprocessError, OSError) as error:
                _add(local_name, record["entry"])  # Put the verified original back.
                raise ClaudeMcpError(
                    "Claude Code refused to add the new MCP entry; the original entry was put back."
                ) from error
    if read_entry(local_name) != entry:
        raise ClaudeMcpError("Claude Code did not record exactly the requested MCP entry.")
    _save_record(registry, component_id, local_name, entry)
    lockfile.upsert_standalone(
        "claude-code",
        component_type="mcp",
        name=name,
        component_id=component_id,
        version=version,
        scope="user",
        namespace=namespace,
        slug=slug,
        local_name=local_name,
        version_id=str(version_id) if version_id else None,
        digest=digest_value,
        requested_version=requested_version,
        pin_known=True,
    )
    return str(config_path())


def _guard_automatic(registry: str, component_id: str) -> None:
    marker = os.environ.get("OBSERVAL_AUTO_UPDATE_SHUTDOWN_MARKER")
    cutoff = float(os.environ.get("OBSERVAL_AUTO_UPDATE_NETWORK_CUTOFF", "inf"))
    rows = [
        row
        for row in lockfile.get_all_entries(harness="claude-code")
        if row.get("type") == "mcp" and row.get("scope") == "user" and row.get("id") == component_id
    ]
    if (
        len(rows) != 1
        or rows[0].get("pin_known") is not True
        or rows[0].get("requested_version")
        or rows[0].get("version") != os.environ.get("OBSERVAL_AUTO_UPDATE_EXPECTED_VERSION")
        or not auto_update_policy.policy_status(registry)["effective"]
        or (marker and Path(marker).exists())
        or time.monotonic() + 15 >= cutoff
        or not os.environ.get("OBSERVAL_AUTO_UPDATE_RECOVERY_DIR")
    ):
        raise ClaudeMcpError("Consent, pin intent, session or installed version changed.")
    client.end_startup_network_budget()


def _save_recovery(root: Path, name: str, old: dict, new: dict) -> None:
    from observal_cli import install_recovery

    if root.parent != install_recovery.BACKUP_DIR or root.exists() or root.is_symlink():
        raise ClaudeMcpError("No fresh private MCP recovery location is available.")
    install_recovery.BACKUP_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    root.mkdir(mode=0o700)
    body = json.dumps({"schema": 1, "name": name, "old": old, "new": new}).encode()
    fd = os.open(root / RECOVERY_FILE, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as handle:
        handle.write(body)
        handle.flush()
        os.fsync(handle.fileno())


def recovery_state(root: Path) -> tuple[str, dict] | None:
    """Classify the entry against the saved plan: old, new, missing or foreign."""
    try:
        record = json.loads((root / RECOVERY_FILE).read_text(encoding="utf-8"))
        current = read_entry(record["name"])
    except (OSError, ValueError, KeyError, TypeError):
        return None
    if current == record["old"]:
        return "old", record
    if current == record["new"]:
        return "new", record
    return ("missing" if current is None else "foreign"), record


def restore_if_safe(root: Path) -> bool:
    """Re-add the original only if the entry is absent or already the planned new one."""
    state = recovery_state(root)
    if state is None or state[0] == "foreign":
        return False
    kind, record = state
    try:
        if kind == "new":
            _run("remove", "-s", "user", record["name"])
        if kind in {"new", "missing"}:
            _add(record["name"], record["old"])
        return read_entry(record["name"]) == record["old"]
    except (ClaudeMcpError, subprocess.SubprocessError, OSError, ValueError):
        return False
