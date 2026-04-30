#!/usr/bin/env python3
"""Lightweight Kiro hook script for non-stop events.

Adds the real ``conversation_id`` from the Kiro SQLite database to
every hook payload, then forwards it to Observal. This is faster than
the full enrichment in ``kiro_stop_hook.py`` — it only reads the
conversation_id column, not the multi-MB conversation JSON.

Usage (in a Kiro agent hook):
    python -m observal_cli.hooks.kiro_hook --url http://host/api/v1/telemetry/hooks --agent-name my-agent
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
from pathlib import Path

from observal_cli.hooks._kiro_utils import _find_kiro_cli_pid, _resolve_hooks_url


def _get_kiro_db() -> Path | None:
    """Return the first existing Kiro SQLite database across standard data dirs."""
    candidates = []
    if sys.platform == "win32":
        for var in ("LOCALAPPDATA", "APPDATA"):
            val = os.environ.get(var)
            if val:
                candidates.append(Path(val) / "kiro-cli" / "data.sqlite3")
    else:
        xdg = os.environ.get("XDG_DATA_HOME")
        if xdg:
            candidates.append(Path(xdg) / "kiro-cli" / "data.sqlite3")
        home = Path.home()
        candidates.append(home / "Library" / "Application Support" / "kiro-cli" / "data.sqlite3")
        candidates.append(home / ".local" / "share" / "kiro-cli" / "data.sqlite3")
    for p in candidates:
        if p.exists():
            return p
    return None


def _add_conversation_id(payload: dict) -> dict:
    """Look up conversation_id and model for this cwd and attach them."""
    kiro_db = _get_kiro_db()
    if not kiro_db:
        return payload

    cwd = payload.get("cwd", "")
    if not cwd:
        return payload

    try:
        conn = sqlite3.connect(f"file:{kiro_db}?mode=ro", uri=True)
        cur = conn.cursor()
        cur.execute(
            "SELECT conversation_id, value FROM conversations_v2 WHERE key = ? ORDER BY updated_at DESC LIMIT 1",
            (cwd,),
        )
        row = cur.fetchone()
        conn.close()
        if row:
            if row[0]:
                payload["conversation_id"] = row[0]
            if row[1] and not payload.get("model"):
                try:
                    conv = json.loads(row[1])
                    model_id = conv.get("model_info", {}).get("model_id", "")
                    if model_id:
                        payload["model"] = model_id
                except (json.JSONDecodeError, KeyError):
                    pass
    except Exception:
        pass

    return payload


_INJECT_STAMP = Path.home() / ".observal" / ".kiro_inject_stamp"
_INJECT_COOLDOWN = 60  # seconds


def _maybe_auto_inject(url: str):
    """Run _auto_inject_hooks at most once per _INJECT_COOLDOWN seconds."""
    import time

    try:
        if _INJECT_STAMP.exists() and (time.time() - _INJECT_STAMP.stat().st_mtime) < _INJECT_COOLDOWN:
            return
        _auto_inject_hooks(url)
        _INJECT_STAMP.parent.mkdir(parents=True, exist_ok=True)
        _INJECT_STAMP.touch()
    except Exception:
        pass


def _is_observal_hook(h: dict) -> bool:
    """Return True if a hook entry belongs to Observal."""
    cmd = h.get("command", "")
    return "observal_cli" in cmd or "telemetry/hooks" in cmd


def _auto_inject_hooks(url: str):
    """Inject Observal hooks into any Kiro agent configs that lack them.

    Runs only on agentSpawn events so new agents get hooks on first use.
    Replaces any existing Observal hooks to avoid duplicates.
    """
    agents_dir = Path.home() / ".kiro" / "agents"
    if not agents_dir.is_dir():
        return
    hook_py = Path(__file__).resolve()
    stop_py = hook_py.parent / "kiro_stop_hook.py"
    if not stop_py.is_file():
        return

    for af in agents_dir.glob("*.json"):
        if af.stem == "kiro_default":
            continue
        try:
            data = json.loads(af.read_text())
            hooks = data.get("hooks", {})
            name = data.get("name") or af.stem
            if sys.platform == "win32":
                cmd = f"{sys.executable} -m observal_cli.hooks.kiro_hook --url {url} --agent-name {name}"
                stop_cmd = f"{sys.executable} -m observal_cli.hooks.kiro_stop_hook --url {url} --agent-name {name}"
            else:
                cmd = f"KIRO_CLI_PID=$PPID {sys.executable} -m observal_cli.hooks.kiro_hook --url {url} --agent-name {name}"
                stop_cmd = f"KIRO_CLI_PID=$PPID {sys.executable} -m observal_cli.hooks.kiro_stop_hook --url {url} --agent-name {name}"
            desired = {
                "agentSpawn": [{"command": cmd}],
                "userPromptSubmit": [{"command": cmd}],
                "preToolUse": [{"matcher": "*", "command": cmd}],
                "postToolUse": [{"matcher": "*", "command": cmd}],
                "stop": [{"command": stop_cmd}],
            }
            merged = dict(hooks)
            for evt, entries in desired.items():
                existing = [h for h in merged.get(evt, []) if not _is_observal_hook(h)]
                merged[evt] = existing + entries
            data["hooks"] = merged
            af.write_text(json.dumps(data, indent=2) + "\n")
        except Exception:
            pass


def main():
    import urllib.request

    url = ""
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
    if not url:
        url = _resolve_hooks_url()
    if not url:
        sys.exit(0)

    try:
        raw = sys.stdin.read()
        payload = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        sys.exit(0)

    # Ensure service_name is set (sed prefix may be overwritten by Kiro's
    # native fields due to JSON duplicate-key semantics — last key wins).
    payload.setdefault("service_name", "kiro")

    if not payload.get("session_id"):
        env_pid = os.environ.get("KIRO_CLI_PID")
        if env_pid:
            payload["session_id"] = f"kiro-cli-{env_pid}"
        else:
            kiro_pid = _find_kiro_cli_pid()
            if kiro_pid:
                payload["session_id"] = f"kiro-cli-{kiro_pid}"
            else:
                payload["session_id"] = f"kiro-{os.getppid()}"

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

    # Inject metadata from CLI args (used on Windows where sed is unavailable)
    if agent_name:
        payload.setdefault("agent_name", agent_name)
    if model:
        payload.setdefault("model", model)

    payload = _add_conversation_id(payload)

    # Auto-inject hooks into any uninstrumented Kiro agent configs (60s cooldown)
    _maybe_auto_inject(url)

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
