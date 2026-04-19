#!/usr/bin/env python3
"""Kiro stop hook enrichment script.

When a Kiro agent's ``stop`` hook fires, this script:
1. Reads the hook JSON payload from stdin.
2. Queries the Kiro SQLite database for the most recent
   conversation matching the working directory (``cwd``).
3. Extracts per-turn metadata: model_id, input/output char counts,
   credit usage, tools used, and context usage.
4. Merges the enriched fields into the payload and POSTs to Observal.

Usage (in a Kiro agent hook):
    Unix:    cat | python3 /path/to/kiro_stop_hook.py --url http://localhost:8000/api/v1/otel/hooks
    Windows: python -m observal_cli.hooks.kiro_stop_hook --url http://localhost:8000/api/v1/otel/hooks --agent-name my-agent
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


def _enrich(payload: dict) -> dict:
    """Read the Kiro SQLite DB and merge session-level stats into *payload*."""
    kiro_db = _get_kiro_db()
    if not kiro_db.exists():
        return payload

    cwd = payload.get("cwd", "")

    try:
        conn = sqlite3.connect(f"file:{kiro_db}?mode=ro", uri=True)
        cur = conn.cursor()

        # Find the most recent conversation for this cwd
        if cwd:
            cur.execute(
                "SELECT conversation_id, value FROM conversations_v2 WHERE key = ? ORDER BY updated_at DESC LIMIT 1",
                (cwd,),
            )
        else:
            cur.execute("SELECT conversation_id, value FROM conversations_v2 ORDER BY updated_at DESC LIMIT 1")

        row = cur.fetchone()
        conn.close()

        if not row:
            return payload

        conversation_id, value_str = row
        conv = json.loads(value_str)

        # Include the real conversation_id for cross-session linking.
        # The $PPID-based session_id (injected via sed before this script) groups
        # events within a single kiro-cli run. The conversation_id persists across
        # resumed sessions — the dashboard can use it to link related sessions.
        if conversation_id:
            payload["conversation_id"] = conversation_id
    except Exception:
        return payload

    # --- Extract model info ---
    model_info = conv.get("model_info", {})
    model_id = model_info.get("model_id", "")

    # --- Aggregate per-turn metadata ---
    history = conv.get("history", [])
    total_input_chars = 0
    total_output_chars = 0
    turn_count = 0
    models_used: set[str] = set()
    tools_used: list[str] = []
    max_context_pct = 0.0

    for entry in history:
        rm = entry.get("request_metadata")
        if not rm:
            continue
        turn_count += 1
        total_input_chars += rm.get("user_prompt_length", 0)
        total_output_chars += rm.get("response_size", 0)
        mid = rm.get("model_id", "")
        if mid:
            models_used.add(mid)
        ctx_pct = rm.get("context_usage_percentage", 0.0)
        if ctx_pct > max_context_pct:
            max_context_pct = ctx_pct
        for tool_pair in rm.get("tool_use_ids_and_names", []):
            if isinstance(tool_pair, list) and len(tool_pair) >= 2:
                tools_used.append(tool_pair[1])

    # --- Credit usage ---
    utm = conv.get("user_turn_metadata", {})
    usage_info = utm.get("usage_info", [])
    total_credits = 0.0
    for u in usage_info:
        total_credits += u.get("value", 0.0)

    # --- Resolve the actual model used ---
    # If model_id is "auto", try to use per-turn model_ids
    resolved_model = model_id
    if model_id == "auto" and models_used - {"auto"}:
        # Use the most common non-auto model
        non_auto = [m for m in models_used if m != "auto"]
        if non_auto:
            resolved_model = non_auto[0]

    # --- Merge into payload ---
    if resolved_model and not payload.get("model"):
        payload["model"] = resolved_model
    payload["turn_count"] = str(turn_count)
    payload["credits"] = f"{total_credits:.6f}"

    if tools_used:
        # Deduplicate while preserving order
        seen: set[str] = set()
        unique_tools = []
        for t in tools_used:
            if t not in seen:
                unique_tools.append(t)
                seen.add(t)
        payload["tools_used"] = ",".join(unique_tools[:20])

    return payload


def main():
    import urllib.request

    # Parse --url and --agent-name arguments
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

    # Read hook payload from stdin
    try:
        raw = sys.stdin.read()
        payload = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        sys.exit(0)

    payload.setdefault("service_name", "kiro-cli")

    # Inject metadata from CLI args (used on Windows where sed is unavailable)
    if agent_name:
        payload.setdefault("agent_name", agent_name)
    if model:
        payload.setdefault("model", model)

    # Enrich with SQLite data
    payload = _enrich(payload)

    # POST to Observal
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
