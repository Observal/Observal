"""Kiro IDE hook specification for session JSONL push.

Kiro hooks are per-agent in ~/.kiro/agents/<name>.json.
Only 2 events needed: userPromptSubmit and stop (reads JSONL incrementally).
"""

from __future__ import annotations

import sys
from pathlib import Path

KIRO_HOOK_EVENTS = ("userPromptSubmit", "stop")

# Parent of the observal_cli package directory
_PKG_ROOT = str(Path(__file__).resolve().parent.parent.parent)


def _python_cmd() -> str:
    """Return python command with PYTHONPATH set if needed."""
    try:
        import importlib.util

        if importlib.util.find_spec("observal_cli") is not None:
            return sys.executable
    except Exception:
        pass
    if sys.platform == "win32":
        return f'set "PYTHONPATH={_PKG_ROOT}" && {sys.executable}'
    return f"PYTHONPATH={_PKG_ROOT} {sys.executable}"


def build_kiro_hooks(*_args, **_kwargs) -> dict:
    """Build the complete hooks dict for a Kiro agent config.

    Only 2 events: userPromptSubmit and stop.
    Legacy callers may pass (hooks_url, agent_name) — ignored.
    """
    cmd = f"{_python_cmd()} -m observal_cli.hooks.kiro_session_push"
    return {
        "userPromptSubmit": [{"command": cmd}],
        "stop": [{"command": cmd}],
    }
