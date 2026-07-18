# SPDX-FileCopyrightText: 2026 Naraen Rammoorthi <naraen13@gmail.com>
# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""Push VS Code Copilot session data to the Observal server.

Invoked by VS Code Copilot hooks for all events (SessionStart, UserPromptSubmit,
PreToolUse, PostToolUse, Stop). Receives JSON on stdin containing the hook payload
with hook_event_name (snake_case), session_id, transcript_path, and event-specific fields.

This script uses ONLY stdlib (no loguru, no httpx) so it works in any Python
environment without extra dependencies.

Entry point:
    python copilot_vscode_session_push.py
    (called from .github/hooks/run_hook.ps1 via PowerShell piping stdin)
"""

from __future__ import annotations

import json
import pathlib
import sys
import urllib.error
import urllib.request

# Map VS Code PascalCase event names to Copilot CLI JSONL event types
# that the server-side classifier (copilot-cli) recognizes.
_EVENT_TYPE_MAP = {
    "SessionStart": "session.start",
    "UserPromptSubmit": "user.message",
    "PreToolUse": "tool.call",
    "PostToolUse": "tool.result",
    "Stop": "session.end",
}


def main() -> None:
    """Entry point. Never raises -- hooks must not block the harness."""
    try:
        _run()
    except Exception:
        pass
    # VS Code hooks expect JSON output on stdout to confirm success
    sys.stdout.write('{"continue":true}\n')
    sys.stdout.flush()


def _run() -> None:
    raw = sys.stdin.read()
    try:
        event = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return

    if not isinstance(event, dict):
        return

    hook_event = event.get("hook_event_name", "") or event.get("hookEventName", "")
    session_id = event.get("session_id", "") or event.get("sessionId", "")

    if not session_id or not hook_event:
        return

    # Load config
    cfg_path = pathlib.Path.home() / ".observal" / "config.json"
    if not cfg_path.exists():
        return

    try:
        cfg = json.loads(cfg_path.read_text())
    except Exception:
        return

    server_url = cfg.get("server_url", "").rstrip("/")
    token = cfg.get("api_key", "") or cfg.get("access_token", "")

    if not server_url or not token:
        return

    # Track offset per session to avoid deduplication
    state_file = pathlib.Path.home() / ".observal" / "copilot_hook_state.json"
    state: dict = {}
    if state_file.exists():
        try:
            state = json.loads(state_file.read_text())
        except Exception:
            state = {}

    session_state = state.get(session_id, {"offset": 0})
    current_offset = session_state["offset"]

    # NOTE: Do NOT reset offset on SessionStart. VS Code reuses the same
    # session_id for multi-turn conversations within a chat window.
    # Resetting would cause dedup collisions with earlier events.

    cwd = event.get("cwd", "")

    # Build synthetic line using Copilot CLI envelope format
    event_type = _EVENT_TYPE_MAP.get(hook_event, "session.start")

    event_body: dict = {"type": event_type}
    if hook_event == "UserPromptSubmit":
        event_body["content"] = event.get("prompt", "")
    elif hook_event == "PreToolUse":
        event_body["name"] = event.get("tool_name", "")
        tool_input = event.get("tool_input", {})
        # Ensure tool_input is serializable (it may be a string or dict)
        if isinstance(tool_input, str):
            try:
                tool_input = json.loads(tool_input)
            except Exception:
                tool_input = {"raw": tool_input}
        event_body["input"] = tool_input
    elif hook_event == "PostToolUse":
        event_body["name"] = event.get("tool_name", "")
        tool_result = event.get("tool_response", event.get("tool_result", ""))
        if isinstance(tool_result, dict):
            event_body["output"] = tool_result.get("text_result_for_llm", json.dumps(tool_result))
        else:
            event_body["output"] = str(tool_result) if tool_result else ""
    elif hook_event == "SessionStart":
        event_body["source"] = event.get("source", "new")
    elif hook_event == "Stop":
        event_body["reason"] = event.get("stop_reason", "session_end")

    synthetic = json.dumps(
        {
            "agentId": session_id,
            "ts": event.get("timestamp", ""),
            "event": event_body,
        }
    )

    payload = {
        "session_id": session_id,
        "harness": "copilot",
        "hook_event": hook_event,
        "lines": [synthetic],
        "start_offset": current_offset,
        "cwd": cwd,
    }

    # Mark as final on Stop
    if hook_event == "Stop":
        payload["final"] = True

    # POST to ingest endpoint
    url = f"{server_url}/api/v1/ingest/session"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    data = json.dumps(payload).encode()

    try:
        req = urllib.request.Request(url, data=data, headers=headers, method="POST")
        resp = urllib.request.urlopen(req, timeout=5)
        if resp.status < 300:
            current_offset += 1
            state[session_id] = {"offset": current_offset}
            try:
                state_file.write_text(json.dumps(state))
            except Exception:
                pass
    except Exception:
        pass


if __name__ == "__main__":
    main()
