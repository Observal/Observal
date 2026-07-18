# SPDX-FileCopyrightText: 2026 Naraen Rammoorthi <naraen13@gmail.com>
# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""Push Copilot CLI session data to the Observal server.

Invoked by Copilot CLI hooks for all events (sessionStart, sessionEnd,
userPromptSubmitted, preToolUse, postToolUse). Receives JSON on stdin
containing the hook payload, reads incremental lines from events.jsonl,
and POSTs combined data to the Observal ingest endpoint.

Entry point:
    python -m observal_cli.hooks.copilot_cli_session_push
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
from observal_cli.sessions.copilot_cli import find_active_session


def main(home: Path | None = None) -> None:
    """Main entry point. Never raises -- hooks must not block the CLI."""
    try:
        _run(home=home)
    except Exception:
        pass
    # VS Code hooks expect JSON output on stdout to confirm success
    sys.stdout.write('{"continue":true}\n')
    sys.stdout.flush()


def _run(home: Path | None = None) -> None:
    # Read hook payload from stdin
    raw = sys.stdin.read()
    try:
        event = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return

    if not isinstance(event, dict):
        return

    cwd: str = event.get("cwd", "")
    timestamp = event.get("timestamp", "")

    # Map Copilot CLI event to Observal hook event name
    hook_event = _resolve_hook_event(event)

    config = load_config(home=home)
    if config is None:
        return

    # Use sessionId from stdin if provided
    # VS Code PascalCase format sends "session_id" (snake_case)
    # Copilot CLI camelCase format sends "sessionId"
    session_id = event.get("sessionId", "") or event.get("session_id", "")

    # VS Code provides transcript_path directly — use it if available
    transcript_path = event.get("transcript_path", "") or event.get("transcriptPath", "")
    jsonl_path: Path | None = None
    if transcript_path:
        tp = Path(transcript_path)
        if tp.exists():
            jsonl_path = tp

    # Copilot CLI: look up by session_id directly (avoids race with find_active_session)
    if not jsonl_path and session_id:
        from observal_cli.sessions.copilot_cli import find_session_jsonl

        jsonl_path = find_session_jsonl(session_id, home=home)

    # Only fall back to find_active_session if we have NO session_id at all.
    # Never fall back when session_id is known but file doesn't exist yet
    # (race condition: hook fires before JSONL file is created).
    if not jsonl_path and not session_id:
        jsonl_path = find_active_session(cwd, home=home)

    # Derive session_id from the events.jsonl path if not in stdin
    if not session_id:
        if jsonl_path and jsonl_path.exists():
            session_id = jsonl_path.parent.name
        elif cwd:
            import hashlib

            session_id = hashlib.sha256(cwd.encode()).hexdigest()[:16]
        else:
            return

    offset, line_count = read_cursor(session_id, home=home)

    # Read new lines from events.jsonl if available
    # Skip JSONL reading on sessionStart — Copilot CLI may send the previous
    # session's ID on this event, and there's no meaningful JSONL to read
    # at session start anyway.
    lines: list[str] = []
    bytes_read = 0
    if jsonl_path and jsonl_path.exists() and hook_event not in ("SessionStart", "sessionStart"):
        lines, bytes_read = read_new_lines(jsonl_path, offset=offset)

    # Always push if we have a hook event (VS Code sends valuable stdin data)
    # Even without JSONL lines, the hook event itself is worth recording
    is_session_end = hook_event in ("sessionEnd", "Stop", "SessionEnd")
    # VS Code PascalCase format uses "hook_event_name", CLI format uses "hookEventName"
    has_hook_event = event.get("hookEventName") or event.get("hook_event_name")
    if not lines and not is_session_end and not has_hook_event:
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
        session_jsonl=jsonl_path,
    )
    # Detect harness: if hook_event_name or hookEventName is in stdin, this is VS Code Copilot
    if event.get("hookEventName") or event.get("hook_event_name"):
        payload["harness"] = "copilot"
    else:
        payload["harness"] = "copilot-cli"

    # Include the stdin hook payload as metadata
    if timestamp:
        payload["hook_timestamp"] = timestamp

    # Include raw hook event data for VS Code hooks (tool_name, prompt, etc.)
    # VS Code PascalCase format uses "hook_event_name", CLI format uses "hookEventName"
    hook_event_name = event.get("hookEventName", "") or event.get("hook_event_name", "")
    if hook_event_name:
        payload["hook_input"] = event
        # Build a synthetic raw_line from the VS Code hook input for the session parser
        if not lines:
            synthetic_line = json.dumps(
                {
                    "agentId": session_id,
                    "ts": timestamp,
                    "event": _vscode_event_to_envelope(event),
                }
            )
            payload["lines"] = [synthetic_line]
            payload["line_count"] = 1

    success = post_to_server(
        server_url=config["server_url"],
        access_token=config["access_token"],
        payload=payload,
        config=config,
    )

    if not success:
        log_error(
            f"copilot_cli_session_push: POST failed for session {session_id} (offset {offset}-{new_offset})",
            home=home,
        )
        return

    write_cursor(session_id, new_offset, line_count + len(lines), finalized=is_session_end, home=home)


# Copilot CLI event name -> Observal canonical hook event
_EVENT_MAP: dict[str, str] = {
    "sessionStart": "SessionStart",
    "sessionEnd": "Stop",
    "userPromptSubmitted": "UserPromptSubmit",
    "preToolUse": "PreToolUse",
    "postToolUse": "PostToolUse",
}


def _resolve_hook_event(event: dict) -> str:
    """Resolve the Observal hook event name from the stdin payload.

    VS Code PascalCase format includes hook_event_name (snake_case field).
    Some older versions may use hookEventName (camelCase field).
    Copilot CLI does not include either; we infer from payload shape.
    """
    # VS Code includes the event name directly (snake_case or camelCase field)
    hook_event_name = event.get("hookEventName", "") or event.get("hook_event_name", "")
    if hook_event_name:
        return hook_event_name

    # Copilot CLI: infer from payload shape
    if "source" in event or "initialPrompt" in event or "initial_prompt" in event:
        return "SessionStart"
    if "reason" in event:
        return "Stop"
    if "prompt" in event:
        return "UserPromptSubmit"
    if "toolResult" in event or "tool_result" in event:
        return "PostToolUse"
    if "toolName" in event or "tool_name" in event:
        return "PreToolUse"
    return "UserPromptSubmit"  # default fallback


# VS Code hook_event_name -> events.jsonl event type
_VSCODE_TO_EVENT_TYPE: dict[str, str] = {
    "SessionStart": "session.start",
    "UserPromptSubmit": "user.message",
    "PreToolUse": "tool.call",
    "PostToolUse": "tool.result",
    "Stop": "session.end",
    "SessionEnd": "session.end",
}


def _vscode_event_to_envelope(event: dict) -> dict:
    """Convert VS Code hook stdin payload to a copilot-cli envelope event dict.

    Handles both PascalCase format (hook_event_name, snake_case fields)
    and legacy camelCase format (hookEventName, camelCase fields).
    """
    hook_event_name = event.get("hookEventName", "") or event.get("hook_event_name", "")
    event_type = _VSCODE_TO_EVENT_TYPE.get(hook_event_name, "session.start")

    envelope_event: dict = {"type": event_type}

    if hook_event_name == "UserPromptSubmit":
        envelope_event["content"] = event.get("prompt", "")
    elif hook_event_name == "PreToolUse":
        envelope_event["name"] = event.get("tool_name", "") or event.get("toolName", "")
        envelope_event["input"] = event.get("tool_input", event.get("toolArgs", {}))
    elif hook_event_name == "PostToolUse":
        envelope_event["name"] = event.get("tool_name", "") or event.get("toolName", "")
        tool_result = event.get("tool_result", event.get("toolResult", {}))
        if isinstance(tool_result, dict):
            envelope_event["output"] = tool_result.get("text_result_for_llm", tool_result.get("textResultForLlm", ""))
        else:
            envelope_event["output"] = str(tool_result)
    elif hook_event_name == "SessionStart":
        envelope_event["source"] = event.get("source", "new")
    elif hook_event_name in ("Stop", "SessionEnd"):
        envelope_event["reason"] = event.get("reason", event.get("stop_reason", event.get("stopReason", "session_end")))

    return envelope_event


if __name__ == "__main__":
    main()
