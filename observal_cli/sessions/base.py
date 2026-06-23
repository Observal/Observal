# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Shared IO primitives for all harness session push scripts.

These functions are harness-agnostic and handle config loading, offset
tracking, line reading, HTTP posting, and error logging.  Every
hook push script and cmd_reconcile imports from here instead of
duplicating the logic.
"""

from __future__ import annotations

import json
from pathlib import Path

from loguru import logger as optic

# ---------------------------------------------------------------------------
# Offset / cursor state
# ---------------------------------------------------------------------------


def read_cursor(session_id: str, home: Path | None = None) -> tuple[int, int]:
    """Return (byte_offset, line_count) for *session_id* from sync_state.json."""
    if home is None:
        home = Path.home()
    state_file = home / ".observal" / "sync_state.json"
    if state_file.exists():
        try:
            data = json.loads(state_file.read_text())
            entry = data.get(session_id, {})
            return entry.get("offset", 0), entry.get("line_count", 0)
        except Exception:
            pass
    return 0, 0


def write_cursor(
    session_id: str,
    offset: int,
    line_count: int,
    finalized: bool = False,
    home: Path | None = None,
) -> None:
    """Persist updated byte offset and line count for *session_id*.

    ``finalized=True`` marks that the Stop hook completed (or crash recovery
    ran) so the scanner will skip this session.
    """
    if home is None:
        home = Path.home()
    sync_dir = home / ".observal"
    sync_dir.mkdir(parents=True, exist_ok=True)
    state_file = sync_dir / "sync_state.json"

    data: dict = {}
    if state_file.exists():
        try:
            data = json.loads(state_file.read_text())
        except Exception:
            pass

    entry: dict = {"offset": offset, "line_count": line_count}
    if finalized or (session_id in data and data[session_id].get("finalized")):
        entry["finalized"] = True
    data[session_id] = entry
    state_file.write_text(json.dumps(data))


# ---------------------------------------------------------------------------
# File reading
# ---------------------------------------------------------------------------


def read_new_lines(jsonl_path: Path, offset: int) -> tuple[list[str], int]:
    """Read bytes from *offset* to EOF in *jsonl_path*.

    Returns (lines, bytes_read).  Empty lines are filtered.  Lines are raw
    strings - not parsed.  If the file ends without a newline (incomplete
    write in progress), the partial last line is excluded and bytes_read
    is adjusted so the next call re-reads it once complete.
    """
    with open(jsonl_path, "rb") as f:
        f.seek(offset)
        raw = f.read()
    if not raw:
        return [], 0
    text = raw.decode("utf-8", errors="replace")
    # If the file doesn't end with newline, the last "line" is likely a
    # partial write still being flushed by the agent.  Exclude it and
    # adjust bytes_read so we re-read from that point next time.
    if not text.endswith("\n"):
        last_nl = text.rfind("\n")
        if last_nl == -1:
            # No complete line at all - wait for more data
            return [], 0
        text = text[: last_nl + 1]
        bytes_read = len(text.encode("utf-8"))
    else:
        bytes_read = len(raw)
    lines = [ln for ln in text.split("\n") if ln.strip()]
    return lines, bytes_read


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


def load_config(home: Path | None = None) -> dict | None:
    """Read server_url and access_token from ~/.observal/config.json.

    Token priority: api_key (30-day) > access_token (1-hour).
    Returns None when the file is missing or required fields are absent.
    """
    if home is None:
        home = Path.home()
    cfg_file = home / ".observal" / "config.json"
    if not cfg_file.exists():
        return None
    try:
        data = json.loads(cfg_file.read_text())
    except Exception:
        return None
    server_url = data.get("server_url", "").strip()
    access_token = data.get("api_key", "").strip() or data.get("access_token", "").strip()
    if not server_url or not access_token:
        return None
    return {
        "server_url": server_url,
        "access_token": access_token,
        "refresh_token": data.get("refresh_token", "").strip(),
        "_config_path": str(cfg_file),
    }


# ---------------------------------------------------------------------------
# HTTP posting
# ---------------------------------------------------------------------------


def _refresh_access_token(server_url: str, refresh_token: str, config_path: str) -> str | None:
    """Use refresh_token to obtain a new access_token and persist it."""
    import httpx

    url = f"{server_url.rstrip('/')}/api/v1/auth/token/refresh"
    try:
        with httpx.Client(timeout=5.0) as client:
            resp = client.post(url, json={"refresh_token": refresh_token})
            if resp.status_code >= 300:
                return None
            data = resp.json()
            new_token = data.get("access_token", "")
            if not new_token:
                return None
            cfg_path = Path(config_path)
            try:
                cfg = json.loads(cfg_path.read_text())
                cfg["access_token"] = new_token
                if data.get("refresh_token"):
                    cfg["refresh_token"] = data["refresh_token"]
                cfg_path.write_text(json.dumps(cfg, indent=2))
            except Exception:
                pass
            return new_token
    except Exception:
        return None


def post_to_server(server_url: str, access_token: str, payload: dict, config: dict | None = None) -> bool:
    """POST *payload* to the ingest endpoint.

    On 401, attempts one token refresh then retries.
    Returns True on HTTP 2xx, False on any error.
    """
    import time

    import httpx

    _t0 = time.perf_counter()
    url = "{}/api/v1/ingest/session".format(server_url.rstrip("/"))
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }
    session_id = payload.get("session_id", "?")[:12]
    line_count = len(payload.get("lines", []))

    try:
        with httpx.Client(timeout=10.0) as client:
            response = client.post(url, json=payload, headers=headers)
            if response.status_code < 300:
                _elapsed = (time.perf_counter() - _t0) * 1000
                optic.debug("uploaded {} lines for session {} ({:.0f}ms)", line_count, session_id, _elapsed)
                return True
            if response.status_code == 401 and config:
                optic.debug("got 401, attempting token refresh")
                refresh_token = config.get("refresh_token", "")
                config_path = config.get("_config_path", "")
                if refresh_token and config_path:
                    new_token = _refresh_access_token(server_url, refresh_token, config_path)
                    if new_token:
                        headers["Authorization"] = f"Bearer {new_token}"
                        retry = client.post(url, json=payload, headers=headers)
                        if retry.status_code < 300:
                            _elapsed = (time.perf_counter() - _t0) * 1000
                            optic.debug("uploaded {} lines after token refresh ({:.0f}ms)", line_count, _elapsed)
                            return True
            optic.warning(
                "ingest POST returned {} for session {} - server rejected the payload",
                response.status_code,
                session_id,
            )
            return False
    except Exception as e:
        _elapsed = (time.perf_counter() - _t0) * 1000
        optic.error(
            "ingest POST failed for session {} after {:.0f}ms: {} - lines are buffered locally but not on server",
            session_id,
            _elapsed,
            e,
        )
        return False


# ---------------------------------------------------------------------------
# Chunked posting
# ---------------------------------------------------------------------------

MAX_CHUNK_SIZE = 500


def post_lines_chunked(
    server_url: str,
    access_token: str,
    session_id: str,
    lines: list[str],
    start_offset: int,
    hook_event: str,
    line_count_before: int,
    new_offset: int = 0,
    cwd: str = "",
    parent_session_id: str | None = None,
    session_jsonl: Path | None = None,
    harness: str = "claude-code",
    config: dict | None = None,
    extra_fields: dict | None = None,
) -> bool:
    """Post lines to ingest in chunks of MAX_CHUNK_SIZE.

    Returns True if ALL chunks succeed, False on first failure.
    Callers should only advance the cursor on True.
    """
    if not lines:
        return True

    total_chunks = (len(lines) + MAX_CHUNK_SIZE - 1) // MAX_CHUNK_SIZE

    for i in range(0, len(lines), MAX_CHUNK_SIZE):
        chunk = lines[i : i + MAX_CHUNK_SIZE]
        chunk_index = i // MAX_CHUNK_SIZE
        is_last = chunk_index == total_chunks - 1

        payload = build_payload(
            session_id=session_id,
            lines=chunk,
            start_offset=line_count_before + i,
            hook_event=hook_event,
            line_count_before=line_count_before + i,
            new_offset=new_offset if is_last else 0,
            cwd=cwd,
            parent_session_id=parent_session_id,
            session_jsonl=session_jsonl,
            harness=harness,
        )
        payload["harness"] = harness
        # Only mark final on the last chunk if the hook_event warrants it
        if not is_last:
            payload.pop("final", None)
            payload.pop("total_line_count", None)
            payload.pop("total_offset", None)
        if extra_fields:
            payload.update(extra_fields)

        success = post_to_server(
            server_url=server_url,
            access_token=access_token,
            payload=payload,
            config=config,
        )
        if not success:
            return False

        # On first chunk, upload layer snapshot if hash changed
        if i == 0 and payload.get("layer_hash"):
            _maybe_upload_layer_snapshot(
                server_url=server_url,
                access_token=access_token,
                layer_hash=payload["layer_hash"],
                harness=harness,
                cwd=cwd,
                config=config,
            )

    return True


# ---------------------------------------------------------------------------
# Payload construction
# ---------------------------------------------------------------------------


def build_payload(
    session_id: str,
    lines: list[str],
    start_offset: int,
    hook_event: str,
    line_count_before: int,
    new_offset: int = 0,
    cwd: str = "",
    parent_session_id: str | None = None,
    session_jsonl: Path | None = None,
    harness: str = "claude-code",
) -> dict:
    """Construct the JSON body for the ingest endpoint.

    Defaults harness telemetry to ``claude-code``; callers override ``payload["harness"]``
    for other harnesses.
    """
    agent_id, agent_version = _resolve_agent(cwd, lines, session_jsonl, harness=harness)
    layer_hash = _get_cached_layer_hash(session_id, cwd)
    payload: dict = {
        "session_id": session_id,
        "harness": "claude-code",
        "agent_id": agent_id,
        "agent_version": agent_version,
        "layer_hash": layer_hash,
        "lines": lines,
        "start_offset": start_offset,
        "hook_event": hook_event,
        "parent_session_id": parent_session_id,
    }
    if hook_event == "Stop":
        payload["final"] = True
        payload["total_line_count"] = line_count_before + len(lines)
        payload["total_offset"] = new_offset
        _evict_layer_hash_cache(session_id)
    return payload


# Per-session layer_hash cache: avoids re-scanning harness dirs on every chunk
_layer_hash_cache: dict[str, str | None] = {}


def _get_cached_layer_hash(session_id: str, cwd: str) -> str | None:
    """Return cached layer_hash for this session, computing once on first call."""
    if session_id not in _layer_hash_cache:
        _layer_hash_cache[session_id] = _compute_layer_hash_safe(cwd, "claude-code")
    return _layer_hash_cache[session_id]


def _evict_layer_hash_cache(session_id: str) -> None:
    """Remove cached hash when session ends (Stop event)."""
    _layer_hash_cache.pop(session_id, None)


def _compute_layer_hash_safe(cwd: str, harness: str) -> str | None:
    """Compute layer_hash without ever blocking the session push.

    Computes across ALL detected harnesses (not just the session's harness).
    Returns None on any failure.
    """
    try:
        from observal_cli.layer import compute_layer_hash

        return compute_layer_hash(harness=None, project_dir=cwd or None)
    except Exception:
        return None


def _is_layer_canonical() -> bool | None:
    """Check if the current layer state matches lockfile integrity (canonical).

    Returns True if no drift detected, False if files were modified,
    None if unable to determine.
    """
    try:
        from observal_cli.layer import _compute_drift, _detect_active_harnesses, build_layer_manifest
        from observal_cli.lockfile import read_lockfile

        lockfile_data = read_lockfile()
        harnesses_section: dict = {}
        for scan_harness in _detect_active_harnesses():
            harnesses_section[scan_harness] = build_layer_manifest(scan_harness, include_content=False)

        drift = _compute_drift(lockfile_data, harnesses_section)
        return drift["is_canonical"]
    except Exception:
        return None


def _maybe_upload_layer_snapshot(
    server_url: str,
    access_token: str,
    layer_hash: str,
    harness: str,
    cwd: str,
    config: dict | None = None,
) -> None:
    """Upload layer snapshot to server if the hash has changed since last upload.

    Fire-and-forget: never blocks session push on failure.
    Saves the snapshot locally as ~/.observal/layer_snapshot.json (mirror of server).
    """
    try:
        from observal_cli.layer import (
            build_upload_payload,
            needs_upload,
            save_local_snapshot,
        )

        if not needs_upload(layer_hash):
            return

        # Build the full manifest with content
        payload = build_upload_payload(harness, project_dir=cwd or None)

        # POST to server
        import httpx

        url = f"{server_url.rstrip('/')}/api/v1/layer-snapshots"
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        }

        with httpx.Client(timeout=10.0) as client:
            resp = client.post(url, json=payload, headers=headers)
            if resp.status_code < 300:
                # Save locally: same content as what server now has
                save_local_snapshot(payload)
                optic.debug("layer snapshot uploaded and saved locally: hash={}", layer_hash)
            else:
                optic.debug("layer snapshot upload failed: status={}", resp.status_code)
    except Exception as e:
        optic.debug("layer snapshot upload skipped: {}", e)


def _resolve_agent(
    cwd: str,
    lines: list[str],
    session_jsonl: Path | None,
    harness: str = "claude-code",
) -> tuple[str | None, str | None]:
    """Resolve agent identity from explicit metadata and the lockfile.

    Kiro attribution is UUID-only via OBSERVAL_AGENT_ID. The lockfile is the
    source of truth for the installed version; cwd must not guess Kiro agents.
    """
    import os

    env_agent_id = os.environ.get("OBSERVAL_AGENT_ID", "")
    if env_agent_id:
        lockfile_entry = _lookup_lockfile_agent_by_id(env_agent_id, harness=harness)
        if lockfile_entry:
            return lockfile_entry.get("id"), lockfile_entry.get("version")
        optic.warning("OBSERVAL_AGENT_ID={} not found in lockfile for harness={}", env_agent_id, harness)
        return None, None

    if harness == "kiro":
        optic.debug("Kiro session has no OBSERVAL_AGENT_ID; leaving unattributed")
        return None, None

    # Resolve agent name from env var or JSONL
    agent_name: str | None = None

    # 1. Env var for legacy/non-Kiro hooks
    env_agent = os.environ.get("OBSERVAL_AGENT_NAME", "")
    if env_agent:
        agent_name = env_agent

    # 2. Parse agent-setting from JSONL lines (Claude Code)
    if not agent_name:
        agent_name = _parse_agent_from_lines(lines)

    # Look up version from lockfile. Agent name is the reliable signal for per-agent hooks.
    lockfile_entry = _lookup_lockfile_agent(cwd, agent_name=agent_name) if cwd or agent_name else None

    if agent_name:
        # Only use lockfile version when the entry matches this agent
        agent_id = agent_name
        version = None
        if lockfile_entry:
            lf_name = lockfile_entry.get("name", "")
            lf_id = lockfile_entry.get("id", "")
            if lf_name == agent_name or lf_id == agent_name:
                agent_id = lf_id or lf_name or agent_name
                version = lockfile_entry.get("version")
        return agent_id, version

    # 3. No name from env/JSONL; fall back to lockfile entirely
    if lockfile_entry:
        return lockfile_entry.get("id") or lockfile_entry.get("name"), lockfile_entry.get("version")

    return None, None


def _lookup_lockfile_agent_by_id(agent_id: str, harness: str | None = None) -> dict | None:
    """Find a lockfile agent by UUID."""
    try:
        from observal_cli.lockfile import get_agent_by_id

        return get_agent_by_id(agent_id, harness=harness)
    except Exception as e:
        optic.debug("lockfile agent id lookup failed: {}", e)
    return None


def _lookup_lockfile_agent(cwd: str, agent_name: str | None = None) -> dict | None:
    """Find the lockfile agent for a directory and optional agent name."""
    try:
        from observal_cli.harness_registry import get_valid_harnesses
        from observal_cli.lockfile import read_lockfile

        data = read_lockfile()
        name_matches: list[dict] = []
        for harness in get_valid_harnesses():
            for agent in data.get("harnesses", {}).get(harness, {}).get("agents", []):
                same_dir = bool(cwd) and agent.get("directory") == cwd
                same_agent = agent_name and (agent.get("name") == agent_name or agent.get("id") == agent_name)
                if agent_name:
                    if same_agent and same_dir:
                        return agent
                    if same_agent:
                        name_matches.append(agent)
                elif same_dir:
                    return agent
        if name_matches:
            for agent in name_matches:
                if agent.get("scope") != "project":
                    return agent
            return name_matches[0]
    except Exception as e:
        optic.debug("lockfile agent lookup failed: {}", e)
    return None


def _parse_agent_from_lines(lines: list[str]) -> str | None:
    """Extract agent name from Claude Code agent-setting JSONL line.

    Claude Code writes a line like:
      {"type": "agent-setting", "agentSetting": "my-agent", ...}
    at the start of a session when an agent is active.
    """
    for raw in lines:
        if "agent-setting" not in raw:
            continue
        try:
            entry = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            continue
        if entry.get("type") == "agent-setting":
            name = entry.get("agentSetting") or entry.get("agentName") or entry.get("name")
            if name:
                return name
    return None


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------


def log_error(message: str, home: Path | None = None) -> None:
    """Append a single-line error entry to ~/.observal/sync.log."""
    if home is None:
        home = Path.home()
    log_dir = home / ".observal"
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        import datetime

        ts = datetime.datetime.now().isoformat(timespec="seconds")
        with open(log_dir / "sync.log", "a") as f:
            f.write(f"{ts} {message}\n")
    except Exception:
        pass
