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
    python -m observal_cli.hooks.kiro_stop_hook --url http://host/api/v1/telemetry/hooks --agent-name my-agent
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import sys
import time
from pathlib import Path

from observal_cli.hooks._kiro_utils import _find_kiro_cli_pid, _resolve_hooks_url

_DEBUG = os.environ.get("OBSERVAL_DEBUG") == "1"
_LOG_PATH = Path.home() / ".observal" / "hook-debug.log"

logger = logging.getLogger(__name__)


def _debug(msg: str) -> None:
    """Write debug message to log file when OBSERVAL_DEBUG=1."""
    if not _DEBUG:
        return
    try:
        _LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with _LOG_PATH.open("a") as f:
            f.write(f"[kiro_stop_hook] {msg}\n")
    except Exception:
        pass


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


def _read_conversation(kiro_db: Path, cwd: str) -> tuple[str, dict] | None:
    """Read the most recent conversation for *cwd* from Kiro's SQLite DB."""
    conn = sqlite3.connect(f"file:{kiro_db}?mode=ro", uri=True)
    cur = conn.cursor()
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
        return None
    conversation_id, value_str = row
    return conversation_id, json.loads(value_str)


def _read_session_file(session_id: str, retries: tuple = (0.5, 1.0, 2.0)) -> dict | None:
    """Read a Kiro session JSON file by session_id, retrying if not yet written."""
    candidates = [session_id]
    for prefix in ("kiro-cli-", "kiro-"):
        if session_id.startswith(prefix):
            candidates.append(session_id[len(prefix) :])

    sessions_dir = Path.home() / ".kiro" / "sessions" / "cli"
    if not sessions_dir.is_dir():
        return None

    for _attempt, delay in enumerate((-1, *retries)):
        if delay >= 0:
            time.sleep(delay)
        for sid in candidates:
            p = sessions_dir / f"{sid}.json"
            if p.exists():
                try:
                    return json.loads(p.read_text())
                except Exception:
                    return None

    return None


def _enrich(payload: dict) -> dict:
    """Read the Kiro session file and merge session-level stats into *payload*."""
    session_id = payload.get("session_id", "")
    cwd = payload.get("cwd", "")
    _debug(f"session_id={session_id}, cwd={cwd}")

    session = None

    # Try reading from session file first (Kiro 2.2+)
    if session_id:
        session = _read_session_file(session_id)

    # Fall back to most recent session matching cwd
    if not session:
        sessions_dir = Path.home() / ".kiro" / "sessions" / "cli"
        if sessions_dir.is_dir() and cwd:
            try:
                candidates = sorted(sessions_dir.glob("*.json"), key=lambda f: f.stat().st_mtime, reverse=True)
                for f in candidates[:10]:
                    try:
                        data = json.loads(f.read_text())
                        if data.get("cwd") == cwd:
                            session = data
                            break
                    except Exception:
                        continue
            except Exception:
                pass

    if not session:
        # Last resort: try SQLite (Kiro < 2.2)
        kiro_db = _get_kiro_db()
        if kiro_db:
            try:
                result = _read_conversation(kiro_db, cwd)
                if not result:
                    for delay in (0.5, 1.0, 1.5):
                        time.sleep(delay)
                        result = _read_conversation(kiro_db, cwd)
                        if result:
                            break
                if result:
                    conversation_id, conv = result
                    if conversation_id:
                        payload["conversation_id"] = conversation_id
                    utm = conv.get("user_turn_metadata", {})
                    usage_info = utm.get("usage_info", [])
                    total_credits = sum(u.get("value", 0.0) for u in usage_info) if usage_info else None
                    if total_credits is not None:
                        payload["credits"] = f"{total_credits:.6f}"
                    model_id = conv.get("model_info", {}).get("model_id", "")
                    if model_id and not payload.get("model"):
                        payload["model"] = model_id
            except Exception as e:
                _debug(f"SQLite fallback error: {e}")
        return payload

    # --- Extract from session file ---
    conv_meta = session.get("session_state", {}).get("conversation_metadata", {})
    turn_metadatas = conv_meta.get("user_turn_metadatas", [])

    def _has_credits(turns: list) -> bool:
        return any(t.get("metering_usage") for t in turns)

    # Kiro writes metering_usage asynchronously after the stop hook fires.
    # Poll with increasing delays up to ~15s total.
    if not _has_credits(turn_metadatas):
        for delay in (2.0, 3.0, 4.0, 6.0):
            _debug(f"metering_usage empty, retrying after {delay}s...")
            time.sleep(delay)
            fresh = _read_session_file(session_id) if session_id else None
            if fresh:
                session = fresh
                conv_meta = session.get("session_state", {}).get("conversation_metadata", {})
                turn_metadatas = conv_meta.get("user_turn_metadatas", [])
            if _has_credits(turn_metadatas):
                _debug("metering_usage found after retry")
                break

    turn_count = len(turn_metadatas)
    # Only report the latest turn's credits — the stop hook fires after every
    # prompt, so sending the cumulative total causes double-counting on the server.
    latest_turn = turn_metadatas[-1] if turn_metadatas else {}
    total_credits = sum(u.get("value", 0.0) for u in latest_turn.get("metering_usage", []) if u.get("unit") == "credit")
    models_used = {t.get("model_id", "") for t in turn_metadatas if t.get("model_id", "")}
    tools_used: list[str] = []
    for t in turn_metadatas:
        for tool in t.get("builtin_tool_uses_detail", []):
            name = tool.get("name", "")
            if name:
                tools_used.append(name)

    model_id = session.get("session_state", {}).get("rts_model_state", {}).get("model_info", {}).get("model_id", "")
    resolved_model = model_id
    if model_id == "auto" and models_used - {"auto", ""}:
        resolved_model = next(m for m in models_used if m not in ("auto", ""))

    conv_id = session.get("session_id", "")
    if conv_id and not payload.get("conversation_id"):
        payload["conversation_id"] = conv_id

    if resolved_model and not payload.get("model"):
        payload["model"] = resolved_model
    payload["turn_count"] = str(turn_count)
    if total_credits:
        payload["credits"] = f"{total_credits:.6f}"

    if tools_used:
        seen: set[str] = set()
        unique_tools = [t for t in tools_used if not (t in seen or seen.add(t))]  # type: ignore[func-returns-value]
        payload["tools_used"] = ",".join(unique_tools[:20])

    _debug(f"credits={total_credits}, turn_count={turn_count}")
    return payload


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

    # Read hook payload from stdin
    try:
        raw = sys.stdin.read()
        payload = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        sys.exit(0)

    _debug(f"payload keys: {list(payload.keys())}")
    _debug(f"payload: {json.dumps(payload)[:2000]}")

    payload.setdefault("service_name", "kiro")

    if not payload.get("session_id"):
        # Kiro 2.x sends session_id on agentSpawn/userPromptSubmit but NOT on
        # stop events. Read the session_id persisted by the non-stop hook so
        # credits land on the same session the user sees in the UI.
        session_file = Path.home() / ".observal" / ".kiro-session"
        try:
            if session_file.exists():
                cached = json.loads(session_file.read_text())
                if cached.get("session_id"):
                    payload["session_id"] = cached["session_id"]
                    _debug(f"Reused persisted session_id: {cached['session_id']}")
        except Exception:
            pass

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

    def _post(p: dict) -> None:
        d = json.dumps(p).encode("utf-8")
        r = urllib.request.Request(url, data=d, headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(r, timeout=5):
                pass
        except Exception:
            pass

    # POST the stop event immediately so the server records the correct
    # timestamp/duration, then fork a background child to enrich with
    # credits and POST an update.
    _post(payload)

    if sys.platform != "win32":
        pid = os.fork()
        if pid != 0:
            sys.exit(0)
        os.setsid()

    payload = _enrich(payload)
    _post(payload)


if __name__ == "__main__":
    main()
