# SPDX-FileCopyrightText: 2026 Lokesh Selvam <lokeshselvam7025@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Background worker for Cursor session push HTTP POST.

Spawned by cursor_session_push.py to offload the HTTP POST from the hook
process (which is subject to Cursor's hook timeout). Reads a payload file,
POSTs to the server, and cleans up.

Usage:
    python -m observal_cli.hooks._cursor_post_worker /path/to/payload.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def _log(msg: str) -> None:
    """Write to debug log immediately - used for crash diagnostics."""
    try:
        import datetime

        log_dir = Path.home() / ".observal"
        log_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.datetime.now().isoformat(timespec="seconds")
        with open(log_dir / "cursor_hook_debug.log", "a") as f:
            f.write(f"[{ts}] {msg}\n")
    except Exception:
        pass


def main() -> None:
    _log(f"WORKER_START argv={sys.argv[1:]}")

    if len(sys.argv) < 2:
        _log("WORKER_EXIT: no argv")
        return

    payload_path = Path(sys.argv[1])
    if not payload_path.exists():
        _log(f"WORKER_EXIT: file not found: {payload_path}")
        return

    try:
        data = json.loads(payload_path.read_text())
    except Exception as e:
        _log(f"WORKER_EXIT: json parse error: {e}")
        payload_path.unlink(missing_ok=True)
        return

    payload = data.get("payload")
    server_url = data.get("server_url", "")
    access_token = data.get("access_token", "")
    config = data.get("config", {})
    session_id = data.get("session_id", "")
    offset = data.get("offset", 0)
    new_offset = data.get("new_offset", 0)

    payload_path.unlink(missing_ok=True)

    if not payload or not server_url or not access_token:
        _log(f"WORKER_EXIT: missing fields payload={bool(payload)} url={bool(server_url)} token={bool(access_token)}")
        return

    try:
        from observal_cli.sessions.base import log_error, post_lines_chunked
    except Exception as e:
        _log(f"WORKER_EXIT: import error: {e}")
        return

    try:
        lines = payload.get("lines", [])
        success = post_lines_chunked(
            server_url=server_url,
            access_token=access_token,
            session_id=payload.get("session_id", session_id),
            lines=lines,
            start_offset=payload.get("start_offset", 0),
            hook_event=payload.get("hook_event", "UserPromptSubmit"),
            line_count_before=payload.get("start_offset", 0),
            new_offset=new_offset,
            cwd=payload.get("cwd", ""),
            parent_session_id=payload.get("parent_session_id"),
            ide=payload.get("ide", "cursor"),
            config=config,
        )
    except Exception as e:
        _log(f"WORKER_EXIT: post_lines_chunked raised: {e}")
        log_error(f"cursor_session_push: POST exception for session {session_id}: {e}")
        return

    if not success:
        log_error(f"cursor_session_push: POST failed for session {session_id} (offset {offset}-{new_offset})")

    status = "OK" if success else "FAIL"
    _log(f"WORKER {status}: session={session_id} offset={offset}-{new_offset}")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        _log(f"WORKER_CRASH: {e}")
        raise
