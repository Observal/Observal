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
import time
from pathlib import Path

from loguru import logger as optic

from observal_cli.sessions.base import (
    build_payload,
    load_config,
    log_error,
    post_lines_chunked,
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
    except Exception as e:
        optic.error("kiro_session_push crashed (swallowed to protect IDE): {}", e)


def _read_credits_with_retry(session_id: str, home: Path | None = None, retries: int = 5) -> float | None:
    """Read credits with retries for race conditions on stop events.

    Kiro may not have written the credits JSON by the time the stop hook fires.
    """
    for attempt in range(retries):
        credits = read_kiro_credits(session_id, home=home)
        if credits is not None:
            optic.trace("read Kiro credits on attempt {}: {}", attempt + 1, credits)
            return credits
        if attempt < retries - 1:
            time.sleep(0.5 * (attempt + 1))
    optic.trace("could not read Kiro credits after {} retries", retries)
    return None


def _run(home: Path | None = None) -> None:
    _t0 = time.perf_counter()
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
        optic.trace("could not resolve Kiro session ID, skipping")
        return

    optic.debug("kiro session push: session={}, event={}", session_id[:12], hook_event)

    # Persist session_id for later Stop event resolution
    _h = home if home is not None else Path.home()
    _persist_dir = _h / ".observal"
    _persist_dir.mkdir(parents=True, exist_ok=True)
    (_persist_dir / ".kiro-session").write_text(json.dumps({"session_id": session_id, "hook_event": hook_event}))

    config = load_config(home=home)
    if config is None:
        optic.warning("no Observal config - Kiro session data will not be uploaded")
        return

    jsonl_path = find_kiro_jsonl(session_id, home=home)
    if jsonl_path is None:
        optic.debug("Kiro JSONL file not found for session {}", session_id[:12])
        return

    offset, line_count = read_cursor(session_id, home=home)
    lines, bytes_read = read_new_lines(jsonl_path, offset=offset)

    if not lines:
        is_stop = hook_event.lower() == "stop"
        if is_stop:
            optic.debug("Kiro session {} stopped with no new lines, finalizing cursor", session_id[:12])
            write_cursor(session_id, offset, line_count, finalized=True, home=home)
            credits = _read_credits_with_retry(session_id, home=home)
            if credits is not None:
                optic.debug("sending Kiro credits ({}) for session {}", credits, session_id[:12])
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
        else:
            optic.trace("no new lines for Kiro session {} (offset={})", session_id[:12], offset)
        return

    optic.debug("read {} new lines ({} bytes) from Kiro session {}", len(lines), bytes_read, session_id[:12])

    new_offset = offset + bytes_read
    is_stop = hook_event.lower() == "stop"
    credits = _read_credits_with_retry(session_id, home=home) if is_stop else read_kiro_credits(session_id, home=home)
    extra: dict = {}
    if credits is not None:
        extra["total_credits"] = credits
        optic.trace("attaching credits={} to Kiro payload", credits)

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
        ide="kiro",
        config=config,
        extra_fields=extra or None,
    )

    if not success:
        optic.error(
            "failed to push {} Kiro lines for session {} (offset {}-{}) - "
            "data may be lost unless reconcile picks it up",
            len(lines),
            session_id[:12],
            offset,
            new_offset,
        )
        log_error(
            f"kiro_session_push: POST failed for session {session_id} (offset {offset}-{new_offset})",
            home=home,
        )
        return

    write_cursor(session_id, new_offset, line_count + len(lines), finalized=is_stop, home=home)
    _elapsed = (time.perf_counter() - _t0) * 1000
    optic.debug("pushed {} Kiro lines for session {} ({:.0f}ms)", len(lines), session_id[:12], _elapsed)

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
    except Exception as e:
        optic.trace("could not spawn crash recovery: {}", e)


if __name__ == "__main__":
    main()
