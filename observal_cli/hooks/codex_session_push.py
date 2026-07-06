# SPDX-FileCopyrightText: 2026 Tanvi Reddy
# SPDX-License-Identifier: Apache-2.0

"""Push Codex CLI session data to the Observal server.

Invoked by Codex CLI hooks (UserPromptSubmit, Stop). Discovers the active
session JSONL at ~/.codex/sessions/YYYY/MM/DD/rollout-<timestamp>-<uuid>.jsonl,
reads new lines incrementally, and POSTs to the ingest endpoint.

Entry point:
    python -m observal_cli.hooks.codex_session_push
"""

from __future__ import annotations

import sys
from pathlib import Path

from observal_cli.sessions.base import (
    load_config,
    log_error,
    post_lines_chunked,
    read_cursor,
    read_new_lines,
    write_cursor,
)


def _find_active_session(home: Path | None = None) -> tuple[Path | None, str]:
    """Find the most recently modified Codex session JSONL file.

    Returns (jsonl_path, session_id). Session ID is derived from the filename.
    """
    if home is None:
        home = Path.home()
    sessions_dir = home / ".codex" / "sessions"
    if not sessions_dir.is_dir():
        return None, ""

    # Glob all JSONL files recursively
    candidates = list(sessions_dir.rglob("*.jsonl"))
    if not candidates:
        return None, ""

    # Most recently modified = active session
    candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    jsonl_path = candidates[0]

    # Extract session ID from filename: rollout-<timestamp>-<uuid>.jsonl
    stem = jsonl_path.stem  # e.g. "rollout-2026-06-03T11-43-41-019e8c1d-c2ce-79f1-afbf-5c3ff02d5fdc"
    parts = stem.split("-")
    session_id = "-".join(parts[-5:]) if len(parts) >= 5 else stem

    return jsonl_path, session_id


def main(home: Path | None = None) -> None:
    """Main entry point. Never raises -- hooks must not block the CLI."""
    try:
        _run(home=home)
    except Exception:
        pass


def _run(home: Path | None = None) -> None:
    # Read hook payload from stdin (Codex passes JSON on stdin)
    raw = sys.stdin.read()

    config = load_config(home=home)
    if config is None:
        return

    # Discover active session
    jsonl_path, session_id = _find_active_session(home=home)
    if not jsonl_path or not session_id:
        return

    offset, line_count = read_cursor(session_id, home=home)

    # Read new lines
    lines, bytes_read = read_new_lines(jsonl_path, offset=offset)

    # Determine hook event from stdin payload
    hook_event = "UserPromptSubmit"
    if raw.strip():
        try:
            import json

            event = json.loads(raw)
            if isinstance(event, dict) and (event.get("event") == "Stop" or event.get("type") == "stop"):
                hook_event = "Stop"
        except (ValueError, TypeError):
            pass

    # If no new lines and not a stop event, nothing to push
    is_stop = hook_event == "Stop"
    if not lines and not is_stop:
        return

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
        cwd="",
        session_jsonl=jsonl_path,
        harness="codex",
        config=config,
    )

    if not success:
        log_error(
            f"codex_session_push: POST failed for session {session_id} (offset {offset}-{new_offset})",
            home=home,
        )
        return

    write_cursor(session_id, new_offset, line_count + len(lines), finalized=is_stop, home=home)


if __name__ == "__main__":
    main()
