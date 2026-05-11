# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Push Kiro JSONL session transcript data to the Observal server.

Mirrors observal_cli.hooks.session_push but for Kiro's file layout:

  Session JSONL:  ~/.kiro/sessions/cli/<session_id>.jsonl
  Session sidecar: ~/.kiro/sessions/cli/<session_id>.json
  Cursor state:   ~/.observal/sync_state.json  (shared with Claude Code)

Invoked by Kiro agent hooks for userPromptSubmit and stop events:
    python -m observal_cli.hooks.kiro_session_push

Receives hook event data via stdin (JSON).  Finds the JSONL file by the
session_id UUID in the payload, reads new lines since last push, and POSTs
them to the ingest endpoint.  On Stop, marks the session finalized so the
crash-recovery scanner skips it.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from observal_cli.hooks.session_push import (
    build_payload,
    load_config,
    log_error,
    post_to_server,
    read_cursor,
    read_new_lines,
    write_cursor,
)

# ---------------------------------------------------------------------------
# Kiro-specific helpers
# ---------------------------------------------------------------------------


def find_kiro_jsonl(session_id: str, home: Path | None = None) -> Path | None:
    """Return the Path to a Kiro session JSONL file, or None if not found.

    Kiro stores transcripts at ~/.kiro/sessions/cli/<session_id>.jsonl.
    The session_id is a UUID (e.g. ``08ad8879-476e-4932-a825-3b3575fb2fbd``).
    """
    if not session_id:
        return None
    if home is None:
        home = Path.home()
    path = home / ".kiro" / "sessions" / "cli" / f"{session_id}.jsonl"
    return path if path.exists() else None


def _resolve_session_id(event: dict, home: Path | None = None) -> str:
    """Return the session_id for a Kiro hook event.

    Kiro sends ``session_id`` on userPromptSubmit / agentSpawn, but NOT
    on stop events.  For stop, fall back to the value persisted by the
    non-stop hook in ~/.observal/.kiro-session.
    """
    session_id = event.get("session_id", "")
    if session_id:
        return session_id

    if home is None:
        home = Path.home()
    session_file = home / ".observal" / ".kiro-session"
    try:
        if session_file.exists():
            cached = json.loads(session_file.read_text())
            session_id = cached.get("session_id", "")
    except Exception:
        pass
    return session_id


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main(home: Path | None = None) -> None:
    """Main entry point.  Never raises -- hooks must not break the IDE."""
    try:
        _run(home=home)
    except Exception:
        pass


def _read_kiro_credits(session_id: str, home: Path | None = None) -> float | None:
    """Read total credit usage from the Kiro session companion .json file.

    The .json file (alongside the .jsonl) contains per-turn metering_usage
    with credit values.  We sum ALL turns so the sessions page shows lifetime
    credit spend for the session rather than just the latest turn.

    Returns None if the file is absent or has no metering_usage yet.
    """
    if not session_id:
        return None
    if home is None:
        home = Path.home()
    json_path = home / ".kiro" / "sessions" / "cli" / f"{session_id}.json"
    if not json_path.exists():
        return None
    try:
        session = json.loads(json_path.read_text())
        turns = session.get("session_state", {}).get("conversation_metadata", {}).get("user_turn_metadatas", [])
        total = sum(
            u.get("value", 0.0) for turn in turns for u in turn.get("metering_usage", []) if u.get("unit") == "credit"
        )
        return total if total > 0 else None
    except Exception:
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
    session_id = _resolve_session_id(event, home=home)

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
        # Nothing new — still mark finalized on Stop so recovery skips it.
        # Even with no new lines, send credits if this is a Stop event.
        is_stop = hook_event.lower() == "stop"
        if is_stop:
            write_cursor(session_id, offset, line_count, finalized=True, home=home)
            credits = _read_kiro_credits(session_id, home=home)
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
    # Tag IDE so the server routes to the Kiro parser
    payload["ide"] = "kiro"
    credits = _read_kiro_credits(session_id, home=home)
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

    is_stop = hook_event.lower() == "stop"
    write_cursor(session_id, new_offset, line_count + len(lines), finalized=is_stop, home=home)

    if not is_stop:
        _spawn_crash_recovery()


def _spawn_crash_recovery() -> None:
    """Spawn observal_cli.cmd_reconcile as a detached background process."""
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
