#!/usr/bin/env python3
"""Lightweight Kiro hook script for non-stop events.

Adds the real ``conversation_id`` from the Kiro SQLite database to
every hook payload, then forwards it to Observal. This is faster than
the full enrichment in ``kiro_stop_hook.py`` — it only reads the
conversation_id column, not the multi-MB conversation JSON.

Usage (in a Kiro agent hook):
    Unix:    cat | python3 /path/to/kiro_hook.py --url http://localhost:8000/api/v1/otel/hooks
    Windows: python -m observal_cli.hooks.kiro_hook --url http://localhost:8000/api/v1/otel/hooks --agent-name my-agent
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
from pathlib import Path


def _get_kiro_db() -> Path:
    """Return the platform-appropriate path to the Kiro SQLite database."""
    if sys.platform == "win32":
        local_app_data = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA") or ""
        if local_app_data:
            return Path(local_app_data) / "kiro-cli" / "data.sqlite3"
    return Path.home() / ".local" / "share" / "kiro-cli" / "data.sqlite3"


def _add_conversation_id(payload: dict) -> dict:
    """Look up the conversation_id for this cwd and attach it."""
    kiro_db = _get_kiro_db()
    if not kiro_db.exists():
        return payload

    cwd = payload.get("cwd", "")
    if not cwd:
        return payload

    try:
        conn = sqlite3.connect(f"file:{kiro_db}?mode=ro", uri=True)
        cur = conn.cursor()
        cur.execute(
            "SELECT conversation_id FROM conversations_v2 WHERE key = ? ORDER BY updated_at DESC LIMIT 1",
            (cwd,),
        )
        row = cur.fetchone()
        conn.close()
        if row and row[0]:
            payload["conversation_id"] = row[0]
    except Exception:
        pass

    return payload


def main():
    import urllib.request

    url = "http://localhost:8000/api/v1/otel/hooks"
    agent_name = ""
    model = ""
    args = sys.argv[1:]
    for i, arg in enumerate(args):
        if arg == "--url" and i + 1 < len(args):
            url = args[i + 1]
        elif arg == "--agent-name" and i + 1 < len(args):
            agent_name = args[i + 1]
        elif arg == "--model" and i + 1 < len(args):
            model = args[i + 1]

    try:
        raw = sys.stdin.read()
        payload = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        sys.exit(0)

    # Ensure service_name is set (sed prefix may be overwritten by Kiro's
    # native fields due to JSON duplicate-key semantics — last key wins).
    payload.setdefault("service_name", "kiro-cli")

    # Inject metadata from CLI args (used on Windows where sed is unavailable)
    if agent_name:
        payload.setdefault("agent_name", agent_name)
    if model:
        payload.setdefault("model", model)

    payload = _add_conversation_id(payload)

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
