# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Push JSONL session transcript data to the Observal server.

Invoked by Claude Code hooks as:
    python -m observal_cli.hooks.session_push

Receives hook event data via stdin (JSON).  Reads new lines from the
session JSONL file since last push and POSTs them to the ingest endpoint.
"""

import json
import sys
import time
from pathlib import Path

from loguru import logger as optic

from observal_cli.sessions.base import (
    load_config,
    log_error,
    post_lines_chunked,
    read_cursor,
    read_new_lines,
    write_cursor,
)
from observal_cli.sessions.claude_code import (
    find_jsonl_file,
    get_parent_session_id,
    project_key_from_cwd,
    push_subagent_sessions,
)


def main(home: Path | None = None) -> None:
    """Main entry point.  Never raises -- hooks must not break the IDE."""
    try:
        _run(home=home)
    except Exception as e:
        optic.error("session_push crashed (swallowed to protect IDE): {}", e)


def _run(home: Path | None = None) -> None:
    _t0 = time.perf_counter()
    raw = sys.stdin.read()
    try:
        event = json.loads(raw)
    except Exception:
        optic.trace("stdin was not valid JSON, ignoring")
        return

    hook_event = event.get("hook_event_name", "")
    session_id = event.get("session_id", "")
    cwd = event.get("cwd", "")

    if not session_id:
        optic.trace("no session_id in hook event, skipping")
        return

    optic.debug("session push triggered: session={}, event={}", session_id[:12], hook_event)

    config = load_config(home=home)
    if config is None:
        optic.warning("no Observal config found - session data will not be uploaded")
        return

    project_key = project_key_from_cwd(cwd)
    jsonl_path = find_jsonl_file(session_id, project_key, home=home)
    if jsonl_path is None:
        optic.debug("JSONL file not found for session {} (may not exist yet)", session_id[:12])
        return

    parent_session_id = get_parent_session_id(jsonl_path)
    optic.trace("parent_session_id={}", parent_session_id)

    offset, line_count = read_cursor(session_id, home=home)
    lines, bytes_read = read_new_lines(jsonl_path, offset=offset)

    if not lines:
        optic.trace("no new lines since last push (offset={})", offset)
        return

    optic.debug("read {} new lines ({} bytes) from session {}", len(lines), bytes_read, session_id[:12])

    new_offset = offset + bytes_read
    success = post_lines_chunked(
        server_url=config["server_url"],
        access_token=config["access_token"],
        session_id=session_id,
        lines=lines,
        start_offset=line_count,
        hook_event=hook_event,
        line_count_before=line_count,
        new_offset=new_offset,
        cwd=cwd,
        parent_session_id=parent_session_id,
        session_jsonl=jsonl_path,
        config=config,
    )

    if not success:
        optic.error(
            "failed to push {} lines for session {} (offset {}-{}) - "
            "data may be lost unless reconcile picks it up later",
            len(lines),
            session_id[:12],
            offset,
            new_offset,
        )
        log_error(
            f"session_push: POST failed for session {session_id} (offset {offset}-{new_offset})",
            home=home,
        )
        return

    write_cursor(session_id, new_offset, line_count + len(lines), finalized=False, home=home)
    _elapsed = (time.perf_counter() - _t0) * 1000
    optic.debug(
        "pushed {} lines for session {} ({:.0f}ms)",
        len(lines),
        session_id[:12],
        _elapsed,
    )

    if parent_session_id is None:
        push_subagent_sessions(session_id, jsonl_path, config, cwd=cwd, home=home)

    if hook_event == "Stop":
        optic.debug("session stopped, spawning tail flush for {}", session_id[:12])
        _spawn_tail_flush(session_id)
    else:
        _spawn_crash_recovery()


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
    except Exception as e:
        optic.trace("could not spawn crash recovery: {}", e)


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
    except Exception as e:
        optic.trace("could not spawn tail flush for {}: {}", session_id[:12], e)


if __name__ == "__main__":
    main()
