# SPDX-FileCopyrightText: 2026 SrihariLegend <sriharilegend23@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""Locate immutable DeepSeek JSONL session generations without rewriting their records."""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any

from loguru import logger as optic

from observal_cli.harness.protocol import SessionSource
from observal_cli.sessions.source_reader import source_chunks

_GENERATION = re.compile(r"session(?:\.v([1-9][0-9]*))?\.jsonl(\.zstd)?\Z")
_CURRENT_VERSION = 4


def resolve_dsh_home(home: Path | None = None) -> Path:
    """Return DSH_HOME when set, otherwise the supplied user's ~/.dsh."""
    user_home = home if home is not None else Path.home()
    override = (os.environ.get("DSH_HOME") or "").strip()
    if override:
        if override == "~" or override.startswith("~/"):
            return user_home / override.removeprefix("~/") if override != "~" else user_home
        return Path(override).expanduser().absolute()
    return user_home / ".dsh"


def _code_units(text: str) -> list[int]:
    raw = text.encode("utf-16-le", errors="surrogatepass")
    return [int.from_bytes(raw[i : i + 2], "little") for i in range(0, len(raw), 2)]


def _encode_segment(text: str) -> str:
    if not text:
        raise ValueError("empty session id")
    if text in {".", ".."}:
        return "~002E" * len(text)
    return "".join(
        chr(unit)
        if chr(unit) in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._-"
        else f"~{unit:04X}"
        for unit in _code_units(text)
    )


def _project_key(cwd: str) -> str:
    result = ""
    separator = False
    for unit in _code_units(cwd):
        char = chr(unit)
        if char in "/\\:":
            if not separator:
                result += "-"
            separator = True
        elif char in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._-" and char != "~":
            result += char
            separator = False
        else:
            result += f"~{unit:04X}"
            separator = False
    return f"--{(result.lstrip('-') or 'root')[:251]}--"


def _header(path: Path) -> dict[str, Any] | None:
    first = b""
    try:
        for chunk in source_chunks(path):
            first += chunk
            if b"\n" in first:
                break
        if b"\n" not in first:
            return None
        header = json.loads(first.split(b"\n", 1)[0])
    except (OSError, ValueError) as exc:
        optic.warning("could not read DeepSeek session header at {}: {}", path, exc)
        return None
    if not isinstance(header, dict) or header.get("type") != "session":
        return None
    return header


def _source(path: Path, root: Path) -> SessionSource | None:
    if path.is_symlink() or path.parent.is_symlink() or path.parent.parent.is_symlink() or not path.is_file():
        return None
    header = _header(path)
    if header is None:
        return None
    session_id = header.get("id")
    cwd = header.get("cwd")
    if (
        header.get("version") != _CURRENT_VERSION
        or not isinstance(session_id, str)
        or not session_id
        or (cwd is not None and (not isinstance(cwd, str) or not os.path.isabs(cwd)))
        or type(header.get("createdAt")) is not int
        or header["createdAt"] < 0
        or type(header.get("isSeeded")) is not bool
        or type(header.get("delegationDepth")) is not int
        or header["delegationDepth"] < 0
    ):
        optic.warning("invalid or unsupported DeepSeek v4 header at {}", path)
        return None
    parent = header.get("parentSession")
    if parent is not None and not isinstance(parent, str):
        return None
    if path.parent.name != _encode_segment(session_id) or path.parent.parent != root / (
        _project_key(cwd) if cwd is not None else "_no-cwd"
    ):
        return None
    return SessionSource("deepseek", session_id, path, cwd or "", parent_session_id=parent)


def _entries(directory: Path) -> list[Path]:
    """List one directory independently so an unreadable sibling is skipped."""
    try:
        return sorted(directory.iterdir())
    except OSError as exc:
        optic.warning("could not list DeepSeek session directory {}: {}", directory, exc)
        return []


def _candidates(root: Path, cutoff: float | None = None) -> list[SessionSource]:
    if not root.is_dir() or root.is_symlink():
        return []
    sources: list[SessionSource] = []
    for project in _entries(root):
        if not project.is_dir() or project.is_symlink():
            continue
        for session_dir in _entries(project):
            if not session_dir.is_dir() or session_dir.is_symlink():
                continue
            source = _candidates_for_directory(session_dir, root, cutoff)
            if source is not None:
                sources.append(source)
    return sources


def _roots(home: Path | None, roots: tuple[Path, ...]) -> tuple[Path, ...]:
    """Read literal persistence roots from user/profile patches without evaluating !!js."""
    from observal_cli.shared.deepseek_config import read_entries

    dsh_home = resolve_dsh_home(home)
    patches = [dsh_home / "cordis.patch.yml"]
    for profile in _entries(dsh_home / "profiles") if (dsh_home / "profiles").is_dir() else []:
        if profile.is_dir() and not profile.is_symlink():
            patches.append(profile / "cordis.patch.yml")
    configured: list[Path] = []
    for patch in patches:
        if patch.is_symlink():
            continue
        try:
            entries = read_entries(patch)
        except (OSError, ValueError) as exc:
            optic.warning("could not inspect DeepSeek session persistence patch {}: {}", patch, exc)
            continue
        for entry in entries:
            if entry.get("name") != "@deepseek-ai/dsh-session-persistence-jsonl":
                continue
            config = entry.get("config")
            if not isinstance(config, dict) or "root" not in config:
                continue
            root = config["root"]
            if not isinstance(root, str):
                optic.warning("unsupported dynamic DeepSeek persistence root in {}", patch)
                continue
            if root == "~" or root.startswith("~/"):
                root_path = home if home is not None else Path.home()
                if root != "~":
                    root_path = root_path / root[2:]
            else:
                root_path = Path(root)
            if not root_path.is_absolute():
                optic.warning("unsupported relative DeepSeek persistence root in {}", patch)
                continue
            configured.append(root_path)
    return tuple(dict.fromkeys((dsh_home / "sessions", *configured, *roots)))


def discover_session_sources(
    home: Path | None = None, since_hours: int = 168, *, roots: tuple[Path, ...] = ()
) -> list[SessionSource]:
    """Return recent current-generation sessions under the default or supplied literal roots."""
    cutoff = time.time() - since_hours * 3600
    return sorted(
        (source for root in _roots(home, roots) for source in _candidates(root, cutoff)),
        key=lambda source: str(source.path),
    )


def resolve_session_source(
    event: dict[str, Any], home: Path | None = None, *, roots: tuple[Path, ...] = ()
) -> SessionSource | None:
    """Resolve a hook's ID by matching the committed physical header, not a guessed filename."""
    session_id = event.get("session_id") or event.get("sessionId")
    if not isinstance(session_id, str) or not session_id:
        return None
    cwd = event.get("cwd")
    for root in _roots(home, roots):
        if isinstance(cwd, str) and os.path.isabs(cwd):
            directory = root / _project_key(cwd) / _encode_segment(session_id)
            if directory.is_dir() and not directory.is_symlink():
                selected = _candidates_for_directory(directory, root)
                if selected is not None and selected.session_id == session_id:
                    return selected
        for source in _candidates(root):
            if source.session_id == session_id and (not cwd or cwd == source.cwd):
                return source
    return None


def _candidates_for_directory(directory: Path, root: Path, cutoff: float | None = None) -> SessionSource | None:
    """Select the highest canonical generation before admitting its header."""
    generations = [
        (int(match[1] or 0), bool(match[2]), path)
        for path in _entries(directory)
        if (match := _GENERATION.fullmatch(path.name)) and path.is_file() and not path.is_symlink()
    ]
    if not generations:
        return None
    version, _compressed, path = max(generations, key=lambda item: (item[0], item[1]))
    if version != _CURRENT_VERSION:
        optic.warning("unsupported DeepSeek session generation v{} at {}", version, path)
        return None
    try:
        if cutoff is not None and path.stat().st_mtime < cutoff:
            return None
    except OSError:
        return None
    return _source(path, root)


def related_session_sources(
    source: SessionSource, home: Path | None = None, *, roots: tuple[Path, ...] = ()
) -> list[SessionSource]:
    """Find child session artifacts linked to this session by physical parentSession."""
    return sorted(
        (
            child
            for root in _roots(home, roots)
            for child in _candidates(root)
            if child.parent_session_id == source.session_id
        ),
        key=lambda child: str(child.path),
    )


# ── Session-to-agent attribution ────────────────────────────────────
#
# DeepSeek agents are on-demand skills, and the harness records the model's
# skill tool call in the v4 log. The OBSERVAL_AGENT_ID env that pull writes
# into the MCP plugin config belongs to the harness process and never
# reaches the collector, so the recorded skill call is the only durable
# attribution signal — and it survives restarts and recovery.

_AGENT_SKILL_PREFIX = "observal-"
_resolved_identities: dict[str, tuple[str, str]] = {}
_scanned_stats: set[tuple[str, int, int]] = set()


def _skill_call_agent(record_line: bytes) -> str | None:
    """The observal-<name> skill a tool/call record invokes, if any."""
    try:
        record = json.loads(record_line)
    except ValueError:
        return None
    if not isinstance(record, dict) or record.get("type") != "tool/call":
        return None
    data = record.get("data")
    if not isinstance(data, dict) or data.get("name") != "skill":
        return None
    arguments = data.get("arguments")
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments)
        except ValueError:
            return None
    if not isinstance(arguments, dict):
        return None
    name = arguments.get("name")
    return name if isinstance(name, str) and name.startswith(_AGENT_SKILL_PREFIX) else None


def _first_agent_skill(path: Path) -> str | None:
    """Stream the session log until the first observal-<agent> skill call."""
    pending = b""
    for chunk in source_chunks(path):
        pending += chunk
        while b"\n" in pending:
            line, pending = pending.split(b"\n", 1)
            agent = _skill_call_agent(line)
            if agent:
                return agent
    return _skill_call_agent(pending) if pending else None


def _lockfile_agent_for_skill(skill_name: str) -> dict | None:
    from observal_cli.lockfile import read_lockfile
    from observal_cli.shared.utils import sanitize_name

    # Search every registry section, not just the currently configured one: a
    # session can be collected after the user switched servers, and the agent
    # that was pulled for it is still the one whose skill was invoked. Pulls
    # append entries, so the last name match is the most recent pull of that
    # agent — the one whose server still knows the id. A cross-namespace or
    # cross-registry collision qualifies the local name, so either the registry
    # name or the local name can name the installed skill.
    match: dict | None = None
    for registry in read_lockfile().get("registries", {}).values():
        for agent in registry.get("harnesses", {}).get("deepseek", {}).get("agents", []):
            names = filter(None, (agent.get("name"), agent.get("local_name")))
            if skill_name in {f"observal-{variant}" for name in names for variant in (name, sanitize_name(name))}:
                match = agent
    return match


def resolve_session_agent_identity(session_jsonl: Path | None, cwd: str) -> tuple[str | None, str | None] | None:
    """Attribute a session through the observal-<agent> skill it invoked.

    Returns None when no pulled agent's skill was invoked, deferring to the
    shared resolution. A positive match is pinned per source path (logs are
    append-only), while misses are keyed by size and mtime so a growing
    session is rescanned as later batches arrive.
    """
    if session_jsonl is None or not session_jsonl.is_file():
        return None
    path_key = str(session_jsonl)
    if path_key in _resolved_identities:
        return _resolved_identities[path_key]
    try:
        stat = session_jsonl.stat()
    except OSError:
        return None
    stat_key = (path_key, stat.st_size, stat.st_mtime_ns)
    if stat_key in _scanned_stats:
        return None
    skill = _first_agent_skill(session_jsonl)
    entry = _lockfile_agent_for_skill(skill) if skill else None
    if entry is None:
        if skill:
            optic.debug("DeepSeek session invoked non-agent skill {}", skill)
        _scanned_stats.add(stat_key)
        return None
    identity = (entry.get("id") or entry.get("name"), entry.get("version"))
    _resolved_identities[path_key] = identity
    return identity
