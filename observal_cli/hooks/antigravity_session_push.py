# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Push Antigravity JSONL session transcript data to the Observal server.

Invoked by Antigravity hooks on PreInvocation and Stop events:
    python -m observal_cli.hooks.antigravity_session_push

Input/Output contract (required by agy):
  - Reads JSON from stdin (includes conversationId, transcriptPath, etc.)
  - Must write JSON to stdout:
    - PreInvocation: {} or {"injectSteps": []}
    - Stop: {"decision": ""} to allow normal termination
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from observal_cli.sessions.antigravity import (
    find_antigravity_jsonl,
    resolve_session_id,
)
from observal_cli.sessions.base import (
    build_payload,
    load_config,
    log_error,
    post_to_server,
    read_cursor,
    read_new_lines,
    write_cursor,
)


def main(home: Path | None = None) -> None:
    """Main entry point. Never raises, hooks must not break the IDE.

    Always writes a valid JSON response to stdout so agy does not hang.
    """
    response = {}
    try:
        response = _run(home=home)
    except Exception:
        pass
    finally:
        # agy requires JSON on stdout for all hook types
        sys.stdout.write(json.dumps(response or {}))
        sys.stdout.flush()


def _run(home: Path | None = None) -> dict:
    raw = sys.stdin.read()
    try:
        event = json.loads(raw)
    except Exception:
        event = {}

    # agy sends terminationReason on Stop events, invocationNum on PreInvocation
    if "terminationReason" in event:
        hook_event = "stop"
    elif "invocationNum" in event:
        hook_event = "preinvocation"
    else:
        hook_event = event.get("hook_event_name", "") or event.get("hookEventName", "") or event.get("event", "")

    cwd: str = ""
    # agy sends workspacePaths as a list
    workspace_paths = event.get("workspacePaths", [])
    if workspace_paths:
        cwd = workspace_paths[0]
    elif event.get("cwd"):
        cwd = event["cwd"]

    # agy provides transcriptPath directly (may be a Windows path on WSL)
    transcript_path_str: str = event.get("transcriptPath", "")
    if transcript_path_str:
        transcript_path_str = _resolve_path_for_platform(transcript_path_str)

    if not hook_event:
        _h = home if home is not None else Path.home()
        _sf = _h / ".observal" / ".antigravity-session"
        try:
            if _sf.exists():
                hook_event = json.loads(_sf.read_text()).get("hook_event", "")
        except Exception:
            pass

    session_id = resolve_session_id(event, home=home)
    if not session_id:
        return _hook_response(hook_event)

    # Persist session_id for later sessionEnd resolution
    _h = home if home is not None else Path.home()
    _persist_dir = _h / ".observal"
    _persist_dir.mkdir(parents=True, exist_ok=True)
    (_persist_dir / ".antigravity-session").write_text(json.dumps({"session_id": session_id, "hook_event": hook_event}))

    config = load_config(home=home)
    if config is None:
        return _hook_response(hook_event)

    # Prefer transcriptPath from agy stdin (exact path), fallback to discovery
    jsonl_path: Path | None = None
    if transcript_path_str:
        tp = Path(transcript_path_str)
        if tp.exists():
            jsonl_path = tp
    if jsonl_path is None:
        jsonl_path = find_antigravity_jsonl(session_id, home=home)
    if jsonl_path is None:
        return _hook_response(hook_event)

    offset, line_count = read_cursor(session_id, home=home)
    lines, bytes_read = read_new_lines(jsonl_path, offset=offset)

    if not lines:
        is_stop = hook_event.lower() in ("session_end", "sessionend", "stop")
        if is_stop:
            write_cursor(session_id, offset, line_count, finalized=True, home=home)
        return _hook_response(hook_event)

    new_offset = offset + bytes_read
    payload = build_payload(
        session_id=session_id,
        lines=lines,
        start_offset=line_count,
        hook_event=hook_event,
        line_count_before=line_count,
        new_offset=new_offset,
        cwd=cwd,
    )
    payload["ide"] = "antigravity"

    success = post_to_server(
        server_url=config["server_url"],
        access_token=config["access_token"],
        payload=payload,
    )

    if not success:
        log_error(
            f"antigravity_session_push: POST failed for session {session_id} (offset {offset}-{new_offset})",
            home=home,
        )
        return _hook_response(hook_event)

    is_stop = hook_event.lower() in ("session_end", "sessionend", "stop")
    write_cursor(session_id, new_offset, line_count + len(lines), finalized=is_stop, home=home)

    if not is_stop:
        _spawn_crash_recovery()

    return _hook_response(hook_event)


def _hook_response(hook_event: str) -> dict:
    """Return the appropriate JSON response for the hook event type.

    agy requires:
      PreInvocation: {} or {"injectSteps": []}
      Stop: {"decision": ""} to allow normal termination
    """
    if hook_event.lower() in ("session_end", "sessionend", "stop"):
        return {"decision": ""}
    return {}


def _resolve_path_for_platform(path_str: str) -> str:
    """Convert a Windows path to a WSL path if running under WSL.

    agy on Windows sends paths like C:\\Users\\foo\\..., but the hook
    runs inside WSL and needs /mnt/c/Users/foo/... instead.
    On native Windows or Unix this is a no-op.
    """
    if not path_str:
        return path_str
    # Detect Windows-style path (drive letter) while running on a Unix-like system
    import os

    if os.name == "nt":
        return path_str  # Native Windows, no conversion needed
    # Check for Windows path pattern (e.g. C:\ or C:/)
    if len(path_str) >= 3 and path_str[1] == ":" and path_str[2] in ("\\", "/"):
        # Running on Unix with a Windows path: likely WSL
        import subprocess

        try:
            result = subprocess.run(["wslpath", path_str], capture_output=True, text=True, timeout=5)
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout.strip()
        except Exception:
            pass
        # Manual fallback: C:\Users\foo -> /mnt/c/Users/foo
        drive = path_str[0].lower()
        rest = path_str[3:].replace("\\", "/")
        return f"/mnt/{drive}/{rest}"
    return path_str


def _spawn_crash_recovery() -> None:
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
