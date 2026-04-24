#!/usr/bin/env python3
"""Lightweight Copilot CLI hook script for non-stop events.

Reads the hook JSON payload from stdin, injects Observal metadata
(service_name, session_id, user identity), and forwards it to the
Observal hooks endpoint.

Usage (in ~/.copilot/config.json hooks):
    Unix:    cat | python3 /path/to/copilot_cli_hook.py --url http://localhost:8000/api/v1/otel/hooks
    Windows: python -m observal_cli.hooks.copilot_cli_hook --url http://localhost:8000/api/v1/otel/hooks
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# Copilot CLI sends camelCase fields; normalize to snake_case for the server.
_FIELD_MAP = {
    "sessionId": "session_id",
    "conversationId": "session_id",
    "threadId": "session_id",
    "hookEventName": "hook_event_name",
    "serviceName": "service_name",
    "userId": "user_id",
    "userName": "user_name",
}


def _normalize(payload: dict) -> dict:
    """Map camelCase Copilot CLI fields to the snake_case the server expects."""
    for camel, snake in _FIELD_MAP.items():
        if camel in payload and snake not in payload:
            payload[snake] = payload[camel]
    return payload


def _stable_session_id() -> str:
    """Derive a session ID that stays the same across all hooks in one session.

    Hook commands run as:  copilot (stable) → bash (new per hook) → python3
    os.getppid() returns the bash PID which differs per hook invocation.
    We walk up one level to the grandparent (the copilot process) for stability.
    """
    ppid = os.getppid()
    try:
        import subprocess

        result = subprocess.run(
            ["ps", "-o", "ppid=", "-p", str(ppid)],
            capture_output=True,
            text=True,
            timeout=2,
        )
        gppid = result.stdout.strip()
        if gppid and gppid not in ("0", "1"):
            return f"copilot-cli-{gppid}"
    except Exception:
        pass
    return f"copilot-cli-{ppid}"


def _resolve_hooks_url() -> str:
    """Read hooks URL from config file when no --url is provided."""
    cfg_path = Path.home() / ".observal" / "config.json"
    if cfg_path.exists():
        try:
            cfg = json.loads(cfg_path.read_text())
            server = cfg.get("server_url", "")
            if server:
                return f"{server.rstrip('/')}/api/v1/otel/hooks"
        except Exception:
            pass
    return "http://localhost:8000/api/v1/otel/hooks"


def main():
    import urllib.request

    url = ""
    model = ""
    event_name = ""
    args = sys.argv[1:]
    for i, arg in enumerate(args):
        if arg == "--url" and i + 1 < len(args):
            url = args[i + 1]
        elif arg == "--model" and i + 1 < len(args):
            model = args[i + 1]
        elif arg == "--event-name" and i + 1 < len(args):
            event_name = args[i + 1]
    if not url:
        url = _resolve_hooks_url()

    try:
        raw = sys.stdin.read()
        payload = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        sys.exit(0)

    _normalize(payload)

    # Map Copilot CLI fields to what the server expects.
    # Copilot CLI sends: prompt, initialPrompt, toolName, toolArgs, toolResult
    if not payload.get("tool_name") and "toolName" in payload:
        payload["tool_name"] = payload["toolName"]

    if not payload.get("tool_input"):
        for key in ("prompt", "initialPrompt", "toolArgs"):
            if key in payload:
                val = payload[key]
                payload["tool_input"] = json.dumps(val) if isinstance(val, dict) else str(val)
                break

    if not payload.get("tool_response"):
        # postToolUse sends toolResult: {resultType, textResultForLlm}
        tr = payload.get("toolResult")
        if isinstance(tr, dict):
            payload["tool_response"] = tr.get("textResultForLlm", json.dumps(tr))
        elif isinstance(tr, str):
            payload["tool_response"] = tr

    payload["service_name"] = "copilot-cli"

    if event_name:
        payload["hook_event_name"] = event_name

    if not payload.get("session_id"):
        payload["session_id"] = _stable_session_id()

    # Inject user_id and user_name from Observal config if not already present
    if not payload.get("user_id") or not payload.get("user_name"):
        try:
            cfg_path = Path.home() / ".observal" / "config.json"
            if cfg_path.exists():
                cfg = json.loads(cfg_path.read_text())
                if not payload.get("user_id") and cfg.get("user_id"):
                    payload["user_id"] = cfg["user_id"]
                if not payload.get("user_name") and cfg.get("user_name"):
                    payload["user_name"] = cfg["user_name"]
        except Exception:
            pass

    if model:
        payload.setdefault("model", model)

    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=5):
            pass
    except Exception:
        pass


if __name__ == "__main__":
    main()
