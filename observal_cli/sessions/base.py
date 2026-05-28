# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Shared IO primitives for all IDE session push scripts.

These functions are IDE-agnostic and handle config loading, offset
tracking, line reading, HTTP posting, and error logging.  Every
hook push script and cmd_reconcile imports from here instead of
duplicating the logic.
"""

from __future__ import annotations

import json
from pathlib import Path

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
    strings — not parsed.
    """
    with open(jsonl_path, "rb") as f:
        f.seek(offset)
        raw = f.read()
    if not raw:
        return [], 0
    text = raw.decode("utf-8", errors="replace")
    lines = [ln for ln in text.split("\n") if ln.strip()]
    return lines, len(raw)


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
    import httpx

    url = f"{server_url.rstrip('/')}/api/v1/ingest/session"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }
    try:
        with httpx.Client(timeout=10.0) as client:
            response = client.post(url, json=payload, headers=headers)
            if response.status_code < 300:
                return True
            if response.status_code == 401 and config:
                refresh_token = config.get("refresh_token", "")
                config_path = config.get("_config_path", "")
                if refresh_token and config_path:
                    new_token = _refresh_access_token(server_url, refresh_token, config_path)
                    if new_token:
                        headers["Authorization"] = f"Bearer {new_token}"
                        retry = client.post(url, json=payload, headers=headers)
                        return retry.status_code < 300
            return False
    except Exception:
        return False


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
) -> dict:
    """Construct the JSON body for the ingest endpoint.

    Defaults ide to ``claude-code``; callers override with ``payload["ide"] = ...``
    for other IDEs.
    """
    agent_id, agent_version = _resolve_agent(cwd, lines, session_jsonl)
    payload: dict = {
        "session_id": session_id,
        "ide": "claude-code",
        "agent_id": agent_id,
        "agent_version": agent_version,
        "lines": lines,
        "start_offset": start_offset,
        "hook_event": hook_event,
        "parent_session_id": parent_session_id,
    }
    if hook_event == "Stop":
        payload["final"] = True
        payload["total_line_count"] = line_count_before + len(lines)
        payload["total_offset"] = new_offset
    return payload


def _resolve_agent(cwd: str, lines: list[str], session_jsonl: Path | None) -> tuple[str | None, str | None]:
    """Resolve agent identity from multiple sources (priority order).

    1. OBSERVAL_AGENT_NAME env var (Kiro per-agent hook commands)
    2. agent-setting line in JSONL (Claude Code embeds active agent)
    """
    import os

    # 1. Env var (Kiro per-agent hooks embed this)
    env_agent = os.environ.get("OBSERVAL_AGENT_NAME", "")
    if env_agent:
        return env_agent, None

    # 2. Parse agent-setting from JSONL lines (Claude Code)
    agent_from_jsonl = _parse_agent_from_lines(lines)
    if agent_from_jsonl:
        return agent_from_jsonl, None

    return None, None


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
