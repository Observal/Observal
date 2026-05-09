"""Push JSONL session transcript data to the Observal server.

Invoked by Claude Code hooks as:
    python -m observal_cli.hooks.session_push

Receives hook event data via stdin (JSON).  Reads new lines from the
session JSONL file since last push and POSTs them to the ingest endpoint.

Imports are kept minimal at module level for fast startup.  httpx is
imported only when a request is actually needed.
"""

import json
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Public helpers (tested individually)
# ---------------------------------------------------------------------------


def project_key_from_cwd(cwd: str) -> str:
    """Convert a filesystem path to the Claude project key format.

    e.g. "/home/user/code/proj" -> "-home-user-code-proj"
    """
    return cwd.replace("/", "-")


def find_jsonl_file(session_id: str, project_key: str, home: Path | None = None) -> Path | None:
    """Return the Path to the session JSONL file, or None if not found."""
    if home is None:
        home = Path.home()

    primary = home / ".claude" / "projects" / project_key / f"{session_id}.jsonl"
    if primary.exists():
        return primary

    # Fallback: scan all project directories
    projects_root = home / ".claude" / "projects"
    if projects_root.exists():
        for match in projects_root.glob(f"**/{session_id}.jsonl"):
            return match

    return None


def read_cursor(session_id: str, home: Path | None = None) -> tuple[int, int]:
    """Return (offset, line_count) for the session from the cursor file."""
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
    session_id: str, offset: int, line_count: int, finalized: bool = False, home: Path | None = None
) -> None:
    """Persist updated cursor for the session.

    ``finalized=True`` marks that the Stop hook completed successfully (or
    crash recovery ran), so the crash-recovery scanner will not attempt to
    re-push this session.
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
    if finalized:
        entry["finalized"] = True
    elif session_id in data and data[session_id].get("finalized"):
        # Preserve finalized flag if already set
        entry["finalized"] = True
    data[session_id] = entry
    state_file.write_text(json.dumps(data))


def read_new_lines(jsonl_path: Path, offset: int) -> tuple[list[str], int]:
    """Read bytes from *offset* to EOF in *jsonl_path*.

    Returns (lines, bytes_read).  Lines are raw strings; empty lines are
    filtered out.  The file is not parsed -- lines are sent as-is.
    """
    with open(jsonl_path, "rb") as f:
        f.seek(offset)
        raw = f.read()

    if not raw:
        return [], 0

    text = raw.decode("utf-8", errors="replace")
    lines = [ln for ln in text.split("\n") if ln.strip()]
    return lines, len(raw)


def read_agent_marker(cwd: str, session_jsonl: Path | None = None) -> tuple[str | None, str | None]:
    """Return (agent_id, agent_version) from <cwd>/.observal/agent, or (None, None).

    Written by ``observal pull`` so hooks can attribute sessions to the
    pulled agent without needing OBSERVAL_AGENT_ID in the shell environment.

    Only attributes the session if it was created AFTER the agent was pulled.
    This prevents unrelated sessions in the same directory from being
    incorrectly attributed to an agent.
    """
    try:
        marker = Path(cwd) / ".observal" / "agent"
        data = json.loads(marker.read_text())

        # If marker has a pulled_at timestamp, only attribute sessions started after the pull
        pulled_at = data.get("pulled_at")
        if pulled_at and session_jsonl and session_jsonl.exists():
            from datetime import datetime, timezone

            pull_time = datetime.fromisoformat(pulled_at)
            # Session JSONL file creation time = session start time
            stat = session_jsonl.stat()
            # st_birthtime (macOS/Windows) or st_ctime as fallback (Linux)
            ctime = getattr(stat, "st_birthtime", None) or stat.st_ctime
            session_ctime = datetime.fromtimestamp(ctime, tz=timezone.utc)
            if session_ctime < pull_time:
                return None, None

        return data.get("agent_id"), data.get("agent_version")
    except Exception:
        return None, None


def get_parent_session_id(jsonl_path: Path) -> str | None:
    """Return the parent session ID if *jsonl_path* is a Claude Code subagent file.

    Subagent JSONL files live at:
      ~/.claude/projects/<project>/<parent_session_id>/subagents/<subagent_session_id>.jsonl

    The parent session ID is the directory two levels above the file.
    Returns None for top-level session files.
    """
    parts = jsonl_path.parts
    if len(parts) >= 3 and parts[-2] == "subagents":
        return parts[-3]  # directory above subagents/ is the parent session id
    return None


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
    """Construct the JSON body for the ingest endpoint."""
    agent_id, agent_version = read_agent_marker(cwd, session_jsonl) if cwd else (None, None)
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


def load_config(home: Path | None = None) -> dict | None:
    """Read server_url and access_token from ~/.observal/config.json.

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
    access_token = data.get("access_token", "").strip()
    if not server_url or not access_token:
        return None

    return {"server_url": server_url, "access_token": access_token}


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


def post_to_server(server_url: str, access_token: str, payload: dict) -> bool:
    """POST *payload* to the ingest endpoint.

    Returns True on HTTP 2xx, False on any error.
    httpx is imported here to keep module-level imports lean.
    """
    import httpx

    url = f"{server_url.rstrip('/')}/api/v1/ingest/session"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }
    try:
        with httpx.Client(timeout=5.0) as client:
            response = client.post(url, json=payload, headers=headers)
            return response.status_code < 300
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main(home: Path | None = None) -> None:
    """Main entry point.  Never raises -- hooks must not break the IDE."""
    try:
        _run(home=home)
    except Exception:
        pass


def _run(home: Path | None = None) -> None:
    raw = sys.stdin.read()
    try:
        event = json.loads(raw)
    except Exception:
        return

    hook_event = event.get("hook_event_name", "")
    session_id = event.get("session_id", "")
    cwd = event.get("cwd", "")

    if not session_id:
        return

    config = load_config(home=home)
    if config is None:
        return

    project_key = project_key_from_cwd(cwd)
    jsonl_path = find_jsonl_file(session_id, project_key, home=home)
    if jsonl_path is None:
        return

    parent_session_id = get_parent_session_id(jsonl_path)

    offset, line_count = read_cursor(session_id, home=home)
    lines, bytes_read = read_new_lines(jsonl_path, offset=offset)

    if not lines:
        return

    new_offset = offset + bytes_read
    payload = build_payload(
        session_id=session_id,
        lines=lines,
        start_offset=line_count,
        hook_event=hook_event,
        line_count_before=line_count,
        new_offset=new_offset,
        cwd=cwd,
        parent_session_id=parent_session_id,
        session_jsonl=jsonl_path,
    )

    success = post_to_server(
        server_url=config["server_url"],
        access_token=config["access_token"],
        payload=payload,
    )

    if not success:
        log_error(
            f"session_push: POST failed for session {session_id} (offset {offset}-{new_offset})",
            home=home,
        )
        return

    is_stop = hook_event == "Stop"
    write_cursor(session_id, new_offset, line_count + len(lines), finalized=is_stop, home=home)

    # On every turn (non-Stop), spawn a background crash-recovery subprocess
    # to push tails of sessions whose Stop hook never fired (hard kill/crash).
    if not is_stop:
        _spawn_crash_recovery()


def _spawn_crash_recovery() -> None:
    """Spawn observal_cli.cmd_reconcile as a detached background process.

    Best-effort: any spawn failure is silently swallowed so the hook is
    never disrupted.
    """
    import subprocess

    try:
        subprocess.Popen(
            [sys.executable, "-m", "observal_cli.cmd_reconcile"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except Exception:
        pass


if __name__ == "__main__":
    main()
