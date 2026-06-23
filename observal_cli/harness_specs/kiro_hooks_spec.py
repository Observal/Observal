# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
# SPDX-FileCopyrightText: 2026 Shreem Seth <shreemseth26@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Kiro harness hook specification for session JSONL push.

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


def build_kiro_hooks(*args, **kwargs) -> dict:
    """Build the complete hooks dict for a Kiro agent config.

    Only 2 events: userPromptSubmit and stop.
    Accepts optional agent_id for per-agent attribution.
    """
    agent_id = kwargs.get("agent_id", "") or (args[2] if len(args) > 2 else "")
    cmd = f"{_python_cmd()} -m observal_cli.hooks.kiro_session_push"
    if agent_id:
        if sys.platform == "win32":
            cmd = f'set "OBSERVAL_AGENT_ID={agent_id}" && {cmd}'
        else:
            cmd = f"OBSERVAL_AGENT_ID={agent_id} {cmd}"
    return {
        "userPromptSubmit": [{"command": cmd}],
        "stop": [{"command": cmd}],
    }
