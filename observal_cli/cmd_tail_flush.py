"""Delayed tail flush — captures lines written after the Stop hook fires.

Claude Code writes ~5 lines after Stop (final assistant response with token
usage, turn_duration, hook summary, etc.).  This subprocess is spawned by
session_push.py on Stop, sleeps briefly to let those writes complete, then
pushes any remaining tail lines and marks the session cursor finalized.

Usage (spawned automatically, not user-facing):
    python -m observal_cli.cmd_tail_flush <session_id>
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

# Delay before reading the tail.  Claude Code typically finishes writing
# within 1-2 seconds of Stop, so 3 seconds gives comfortable margin.
_FLUSH_DELAY_SECS = 3

# Maximum retries if the file is still growing (belt-and-suspenders).
_MAX_RETRIES = 2
_RETRY_DELAY_SECS = 2


def tail_flush(session_id: str, home: Path | None = None) -> None:
    """Push any post-Stop lines for *session_id* and mark it finalized."""
    from observal_cli.cmd_reconcile import _find_session_file
    from observal_cli.hooks.session_push import (
        build_payload,
        load_config,
        post_to_server,
        push_subagent_sessions,
        read_cursor,
        read_new_lines,
        write_cursor,
    )

    if home is None:
        home = Path.home()

    config = load_config(home=home)
    if config is None:
        return

    time.sleep(_FLUSH_DELAY_SECS)

    jsonl_path = _find_session_file(session_id, home=home)
    if jsonl_path is None:
        return

    for attempt in range(_MAX_RETRIES + 1):
        offset, line_count = read_cursor(session_id, home=home)
        lines, bytes_read = read_new_lines(jsonl_path, offset)

        if not lines:
            # Nothing new — file didn't grow after Stop. Finalize.
            write_cursor(session_id, offset, line_count, finalized=True, home=home)
            return

        new_offset = offset + bytes_read
        payload = build_payload(
            session_id=session_id,
            lines=lines,
            start_offset=line_count,
            hook_event="Stop",
            line_count_before=line_count,
            new_offset=new_offset,
        )

        success = post_to_server(
            server_url=config["server_url"],
            access_token=config["access_token"],
            payload=payload,
            config=config,
        )

        if success:
            write_cursor(session_id, new_offset, line_count + len(lines), finalized=True, home=home)

            # Also flush any subagent tails that may have grown
            from observal_cli.hooks.session_push import get_parent_session_id

            parent_session_id = get_parent_session_id(jsonl_path)
            if parent_session_id is None:
                # This IS the parent — push subagent tails too
                push_subagent_sessions(session_id, jsonl_path, config, home=home)

            return
        else:
            # Push failed — retry after a short delay
            if attempt < _MAX_RETRIES:
                time.sleep(_RETRY_DELAY_SECS)
            else:
                # Leave un-finalized so crash recovery can pick it up later
                from observal_cli.hooks.session_push import log_error

                log_error(
                    f"tail_flush: POST failed for session {session_id} after {_MAX_RETRIES + 1} attempts",
                    home=home,
                )


def main() -> None:
    """Entry point. Never raises — background processes must not leave zombies."""
    try:
        if len(sys.argv) < 2:
            return
        session_id = sys.argv[1]
        if not session_id:
            return
        tail_flush(session_id)
    except Exception:
        pass


if __name__ == "__main__":
    main()
