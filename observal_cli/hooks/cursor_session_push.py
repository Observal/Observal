# SPDX-FileCopyrightText: 2026 Lokesh Selvam <lokeshselvam7025@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""Push Cursor session transcript data to the Observal server.

Invoked by Cursor hooks as:
    python -m observal_cli.hooks.cursor_session_push

Receives hook event data via stdin (JSON).  Reads new lines from the
transcript file since last push and POSTs them to the ingest endpoint.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from observal_cli.sessions.base import (
    build_payload,
    load_config,
    read_cursor,
    read_new_lines,
    write_cursor,
)
from observal_cli.sessions.cursor import (
    build_usage_line,
    find_cursor_jsonl,
    get_parent_session_id,
    project_key_from_cwd,
)


def _debug_log(msg: str, home: Path | None = None) -> None:
    """Write to debug log immediately - used for crash diagnostics."""
    if home is None:
        home = Path.home()
    try:
        log_dir = home / ".observal"
        log_dir.mkdir(parents=True, exist_ok=True)
        import datetime

        ts = datetime.datetime.now().isoformat(timespec="seconds")
        with open(log_dir / "cursor_hook_debug.log", "a") as f:
            f.write(f"[{ts}] {msg}\n")
    except Exception:
        pass


def main(home: Path | None = None) -> None:
    """Main entry point.  Never raises -- hooks must not break the harness."""
    try:
        _run(home=home)
    except Exception:
        pass


def _run(home: Path | None = None) -> None:
    raw = sys.stdin.read()
    _debug_log(f"STDIN len={len(raw)} payload={raw[:300]}", home=home)

    try:
        event = json.loads(raw)
    except Exception:
        _debug_log("FAIL: invalid JSON", home=home)
        return

    hook_event = event.get("event", "") or event.get("hook_event_name", "")
    session_id = event.get("conversationId", "") or event.get("conversation_id", "") or event.get("session_id", "")
    transcript_path_str = event.get("transcriptPath", "") or event.get("transcript_path", "")
    workspace_path = event.get("workspacePath", "")
    if not workspace_path:
        workspace_roots = event.get("workspace_roots", [])
        workspace_path = workspace_roots[0] if workspace_roots else event.get("cwd", "")
    cwd = workspace_path

    _debug_log(f"PARSED event={hook_event} session={session_id} cwd={cwd}", home=home)

    if not session_id:
        _debug_log("FAIL: no session_id", home=home)
        return

    config = load_config(home=home)
    if config is None:
        _debug_log("FAIL: no config", home=home)
        return

    jsonl_path: Path | None = None
    if transcript_path_str:
        candidate = Path(transcript_path_str)
        if candidate.exists():
            jsonl_path = candidate

    if jsonl_path is None:
        p_key = project_key_from_cwd(cwd)
        jsonl_path = find_cursor_jsonl(session_id, p_key, home=home)
        _debug_log(f"SEARCH key={p_key} found={jsonl_path}", home=home)

    if jsonl_path is None:
        _debug_log("FAIL: jsonl not found", home=home)
        return

    parent_session_id = get_parent_session_id(jsonl_path)

    offset, line_count = read_cursor(session_id, home=home)
    lines, bytes_read = read_new_lines(jsonl_path, offset=offset)

    _debug_log(f"READ offset={offset} lines={len(lines)} bytes={bytes_read}", home=home)

    if not lines:
        _debug_log("SKIP: no new lines", home=home)
        return

    if hook_event.lower() == "stop":
        usage_line = build_usage_line(event)
        if usage_line:
            lines.append(usage_line)

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
    payload["harness"] = "cursor"

    write_cursor(session_id, new_offset, line_count + len(lines), finalized=False, home=home)
    _spawn_post(payload, config, session_id, offset, new_offset, home=home)
    _debug_log(f"SPAWNED POST for {len(lines)} lines offset={offset}-{new_offset}", home=home)

    if hook_event.lower() == "stop":
        _spawn_tail_flush(session_id)
    else:
        _spawn_crash_recovery()


def _spawn_post(
    payload: dict,
    config: dict,
    session_id: str,
    offset: int,
    new_offset: int,
    home: Path | None = None,
) -> None:
    """Spawn a detached subprocess to POST the payload, avoiding Cursor's hook timeout."""
    import subprocess

    if home is None:
        home = Path.home()

    try:
        payload_dir = home / ".observal" / "pending"
        payload_dir.mkdir(parents=True, exist_ok=True)
        payload_file = payload_dir / f"{session_id}_{offset}_{new_offset}.json"
        payload_file.write_text(
            json.dumps(
                {
                    "payload": payload,
                    "server_url": config["server_url"],
                    "access_token": config["access_token"],
                    "config": config,
                    "session_id": session_id,
                    "offset": offset,
                    "new_offset": new_offset,
                }
            )
        )
    except Exception:
        return

    try:
        subprocess.Popen(
            [sys.executable, "-m", "observal_cli.hooks._cursor_post_worker", str(payload_file)],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except Exception:
        pass


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


def _spawn_tail_flush(session_id: str) -> None:
    import subprocess

    try:
        subprocess.Popen(
            [sys.executable, "-m", "observal_cli.cmd_tail_flush", session_id],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except Exception:
        pass


if __name__ == "__main__":
    main()
