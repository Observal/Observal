# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Push Kiro JSONL session transcript data to the Observal server.

Invoked by Kiro agent hooks for userPromptSubmit and stop events:
    python -m observal_cli.hooks.kiro_session_push
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from observal_cli.sessions.base import (
    build_payload,
    load_config,
    log_error,
    post_to_server,
    read_cursor,
    read_new_lines,
    write_cursor,
)
from observal_cli.sessions.kiro import (
    find_kiro_jsonl,
    read_kiro_credits,
    resolve_session_id,
)


def main(home: Path | None = None) -> None:
    """Main entry point.  Never raises -- hooks must not break the IDE."""
    try:
        _run(home=home)
    except Exception:
        pass


def _read_credits_with_retry(session_id: str, home: Path | None = None, retries: int = 3) -> float | None:
    """Read credits with brief retries for race conditions on stop events.

    Kiro may not have written the credits JSON by the time the stop hook fires.
    A short sleep between retries gives Kiro time to flush the file.
    """
    import time

    for attempt in range(retries):
        credits = read_kiro_credits(session_id, home=home)
        if credits is not None:
            return credits
        if attempt < retries - 1:
            time.sleep(0.3)
    return None


def _run(home: Path | None = None) -> None:
    raw = sys.stdin.read()
    try:
        event = json.loads(raw)
    except Exception:
        event = {}

    hook_event: str = event.get("hook_event_name", "") or event.get("hookEventName", "") or event.get("event", "")
    cwd: str = event.get("cwd", "")
    if not hook_event:
        _h = home if home is not None else Path.home()
        _sf = _h / ".observal" / ".kiro-session"
        try:
            if _sf.exists():
                hook_event = json.loads(_sf.read_text()).get("hook_event", "")
        except Exception:
            pass

    session_id = resolve_session_id(event, home=home)
    if not session_id:
        return

    # Persist session_id for later Stop event resolution
    _h = home if home is not None else Path.home()
    _persist_dir = _h / ".observal"
    _persist_dir.mkdir(parents=True, exist_ok=True)
    (_persist_dir / ".kiro-session").write_text(json.dumps({"session_id": session_id, "hook_event": hook_event}))

    config = load_config(home=home)
    if config is None:
        return

    jsonl_path = find_kiro_jsonl(session_id, home=home)
    if jsonl_path is None:
        return

    offset, line_count = read_cursor(session_id, home=home)
    lines, bytes_read = read_new_lines(jsonl_path, offset=offset)

    if not lines:
        is_stop = hook_event.lower() == "stop"
        if is_stop:
            write_cursor(session_id, offset, line_count, finalized=True, home=home)
            credits = _read_credits_with_retry(session_id, home=home)
            if credits is not None:
                payload_credits = build_payload(
                    session_id=session_id,
                    lines=[],
                    start_offset=line_count,
                    hook_event=hook_event,
                    line_count_before=line_count,
                    new_offset=offset,
                    cwd=cwd,
                )
                payload_credits["ide"] = "kiro"
                payload_credits["total_credits"] = credits
                post_to_server(
                    server_url=config["server_url"],
                    access_token=config["access_token"],
                    payload=payload_credits,
                )
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
    )
    payload["ide"] = "kiro"
    is_stop = hook_event.lower() == "stop"
    credits = _read_credits_with_retry(session_id, home=home) if is_stop else read_kiro_credits(session_id, home=home)
    if credits is not None:
        payload["total_credits"] = credits

    success = post_to_server(
        server_url=config["server_url"],
        access_token=config["access_token"],
        payload=payload,
    )

    if not success:
        log_error(
            f"kiro_session_push: POST failed for session {session_id} (offset {offset}-{new_offset})",
            home=home,
        )
        return

    write_cursor(session_id, new_offset, line_count + len(lines), finalized=is_stop, home=home)

    if not is_stop:
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
    except Exception:
        pass


if __name__ == "__main__":
    main()
