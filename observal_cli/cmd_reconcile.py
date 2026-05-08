"""Crash recovery and session reconciliation for Observal CLI.

Two responsibilities:
1. Discovery helpers (_find_claude_sessions_dir, _find_recent_sessions,
   _find_session_file, _parse_session_file) used by the reconcile pipeline
   and the admin `observal ops sync` command.
2. Crash recovery: on the next UserPromptSubmit hook after a session was
   killed before its Stop hook fired, this module detects the stale cursor
   and pushes the remaining JSONL lines so no turns are lost.

Run as a background subprocess from session_push.py:
    python -m observal_cli.cmd_reconcile
"""

from __future__ import annotations

import json
import time
from pathlib import Path

# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


def _find_claude_sessions_dir(home: Path | None = None) -> Path:
    """Return ~/.claude/projects/ (the root of all Claude Code session JSONL files)."""
    if home is None:
        home = Path.home()
    return home / ".claude" / "projects"


def _find_kiro_sessions_dir(home: Path | None = None) -> Path:
    """Return ~/.kiro/sessions/cli/ (the root of all Kiro session JSONL files)."""
    if home is None:
        home = Path.home()
    return home / ".kiro" / "sessions" / "cli"


def _find_recent_sessions(
    since_hours: int = 168,
    home: Path | None = None,
) -> list[tuple[Path, str]]:
    """Return (jsonl_path, session_id) pairs for recently-modified session files.

    Discovers:
    - Top-level files:  ~/.claude/projects/<project>/<session_id>.jsonl
    - Subagent files:   ~/.claude/projects/<project>/<session_id>/subagents/<agent_id>.jsonl
    - Kiro files:       ~/.kiro/sessions/cli/<session_id>.jsonl

    Files older than *since_hours* are excluded.
    """
    cutoff = time.time() - since_hours * 3600
    results: list[tuple[Path, str]] = []

    # Claude Code sessions
    sessions_dir = _find_claude_sessions_dir(home)
    if sessions_dir.exists():
        for project_dir in sessions_dir.iterdir():
            if not project_dir.is_dir():
                continue
            # Top-level session files
            for jsonl_file in project_dir.glob("*.jsonl"):
                try:
                    if jsonl_file.stat().st_mtime >= cutoff:
                        results.append((jsonl_file, jsonl_file.stem))
                except OSError:
                    pass
            # Subagent files under <session_id>/subagents/
            for session_subdir in project_dir.iterdir():
                if not session_subdir.is_dir():
                    continue
                subagents_dir = session_subdir / "subagents"
                if not subagents_dir.is_dir():
                    continue
                for sub_file in subagents_dir.glob("*.jsonl"):
                    try:
                        if sub_file.stat().st_mtime >= cutoff:
                            results.append((sub_file, sub_file.stem))
                    except OSError:
                        pass

    # Kiro sessions
    kiro_dir = _find_kiro_sessions_dir(home)
    if kiro_dir.exists():
        for jsonl_file in kiro_dir.glob("*.jsonl"):
            try:
                if jsonl_file.stat().st_mtime >= cutoff:
                    results.append((jsonl_file, jsonl_file.stem))
            except OSError:
                pass

    return results


def _find_session_file(
    session_id: str,
    home: Path | None = None,
) -> Path | None:
    """Return the Path for *session_id*.jsonl across all supported IDEs.

    Search order:
    1. Claude Code top-level: ~/.claude/projects/<project>/<session_id>.jsonl
    2. Claude Code subagent:  ~/.claude/projects/<project>/<id>/subagents/<session_id>.jsonl
    3. Kiro:                  ~/.kiro/sessions/cli/<session_id>.jsonl
    """
    # --- Claude Code ---
    claude_dir = _find_claude_sessions_dir(home)
    if claude_dir.exists():
        for project_dir in claude_dir.iterdir():
            if not project_dir.is_dir():
                continue
            candidate = project_dir / f"{session_id}.jsonl"
            if candidate.exists():
                return candidate
            for session_subdir in project_dir.iterdir():
                if not session_subdir.is_dir():
                    continue
                sub = session_subdir / "subagents" / f"{session_id}.jsonl"
                if sub.exists():
                    return sub

    # --- Kiro ---
    kiro_path = _find_kiro_sessions_dir(home) / f"{session_id}.jsonl"
    if kiro_path.exists():
        return kiro_path

    return None


def _parse_session_file(path: Path) -> dict:
    """Parse a session JSONL file and return an enrichment summary dict.

    Detects subagent files by path structure (.../subagents/<agent_id>.jsonl).
    """
    parts = path.parts
    is_subagent = len(parts) >= 3 and parts[-2] == "subagents"
    parent_session_id: str | None = None
    subagent_id: str | None = None

    if is_subagent:
        subagent_id = path.stem
        parent_session_id = parts[-3]

    total_input_tokens = 0
    total_output_tokens = 0
    models_seen: set[str] = set()
    conversation_turns = 0
    records: list[dict] = []

    content_types: frozenset[str] = frozenset({"assistant", "user", "system"})

    try:
        for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
            raw = raw.strip()
            if not raw:
                continue
            try:
                record = json.loads(raw)
            except Exception:
                continue

            if record.get("type") in content_types:
                records.append(record)

            if record.get("type") != "assistant":
                continue

            conversation_turns += 1
            message = record.get("message", {})
            usage = message.get("usage", {}) or record.get("usage", {})
            total_input_tokens += usage.get("input_tokens", 0)
            total_output_tokens += usage.get("output_tokens", 0)
            model = record.get("model") or message.get("model")
            if model:
                models_seen.add(model)
    except OSError:
        pass

    return {
        "session_id": parent_session_id or path.stem,
        "is_subagent": is_subagent,
        "parent_session_id": parent_session_id,
        "subagent_id": subagent_id,
        "total_input_tokens": total_input_tokens,
        "total_output_tokens": total_output_tokens,
        "models_used": sorted(models_seen),
        "conversation_turns": conversation_turns,
        "records": records,
    }


# ---------------------------------------------------------------------------
# Crash recovery
# ---------------------------------------------------------------------------

_STALE_MIN_AGE_SECS = 120  # session must be >= 2 min idle before recovering
_STALE_MAX_AGE_SECS = 7 * 24 * 3600  # only recover sessions from the last 7 days


def find_stale_sessions(home: Path | None = None) -> list[dict]:
    """Return sessions in sync_state that have unsynced bytes and are not finalized.

    A session is stale when:
    - Its JSONL file exists and is larger than the cursor byte offset
      (lines were written after the last successful push)
    - It is not marked ``finalized`` (Stop hook fired successfully)
    - The JSONL mtime is between 2 minutes and 7 days old
      (avoids touching an actively-running session)
    """
    if home is None:
        home = Path.home()

    state_file = home / ".observal" / "sync_state.json"
    if not state_file.exists():
        return []

    try:
        state: dict = json.loads(state_file.read_text())
    except Exception:
        return []

    now = time.time()
    stale: list[dict] = []

    for session_id, cursor in state.items():
        if not isinstance(cursor, dict):
            continue
        if cursor.get("finalized"):
            continue

        offset = cursor.get("offset", 0)
        line_count = cursor.get("line_count", 0)

        jsonl_path = _find_session_file(session_id, home=home)
        if jsonl_path is None:
            continue

        try:
            stat = jsonl_path.stat()
        except OSError:
            continue

        if stat.st_size <= offset:
            continue  # nothing new to send

        age = now - stat.st_mtime
        if age < _STALE_MIN_AGE_SECS or age > _STALE_MAX_AGE_SECS:
            continue  # too fresh (still active) or too old

        stale.append(
            {
                "session_id": session_id,
                "jsonl_path": jsonl_path,
                "cursor_offset": offset,
                "cursor_line_count": line_count,
                "file_size": stat.st_size,
            }
        )

    return stale


def recover_stale_session(
    session: dict,
    config: dict,
    home: Path | None = None,
) -> bool:
    """Push the unsynced tail of a stale session and mark it finalized.

    Treats the recovery push as a Stop event so the server integrity check
    can run.  Marks the cursor finalized on success so the session is never
    recovered again.
    """
    from observal_cli.hooks.session_push import (
        build_payload,
        post_to_server,
        read_new_lines,
        write_cursor,
    )

    jsonl_path: Path = session["jsonl_path"]
    session_id: str = session["session_id"]
    cursor_offset: int = session["cursor_offset"]
    cursor_line_count: int = session["cursor_line_count"]

    lines, bytes_read = read_new_lines(jsonl_path, cursor_offset)
    if not lines:
        _mark_finalized(session_id, home=home)
        return True

    new_offset = cursor_offset + bytes_read
    payload = build_payload(
        session_id=session_id,
        lines=lines,
        start_offset=cursor_line_count,
        hook_event="Stop",
        line_count_before=cursor_line_count,
        new_offset=new_offset,
    )
    payload["crash_recovered"] = True

    success = post_to_server(
        server_url=config["server_url"],
        access_token=config["access_token"],
        payload=payload,
    )

    if success:
        write_cursor(
            session_id,
            new_offset,
            cursor_line_count + len(lines),
            home=home,
        )
        _mark_finalized(session_id, home=home)

    return success


def _mark_finalized(session_id: str, home: Path | None = None) -> None:
    """Set finalized=True for *session_id* in sync_state.json."""
    if home is None:
        home = Path.home()
    state_file = home / ".observal" / "sync_state.json"
    try:
        data: dict = json.loads(state_file.read_text()) if state_file.exists() else {}
        entry = data.setdefault(session_id, {})
        entry["finalized"] = True
        state_file.write_text(json.dumps(data))
    except Exception:
        pass


def run_recovery(home: Path | None = None) -> None:
    """Entry point for background crash-recovery subprocess.

    Called by session_push.py via subprocess.Popen on each UserPromptSubmit.
    Scans for stale sessions and pushes their tails; never raises.
    """
    try:
        _run_recovery(home=home)
    except Exception:
        pass


def _run_recovery(home: Path | None = None) -> None:
    from observal_cli.hooks.session_push import load_config

    config = load_config(home=home)
    if config is None:
        return

    stale = find_stale_sessions(home=home)
    for session in stale:
        try:
            recover_stale_session(session, config, home=home)
        except Exception:
            pass


if __name__ == "__main__":
    run_recovery()
