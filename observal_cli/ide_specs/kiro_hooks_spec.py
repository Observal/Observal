"""Kiro IDE hook specification.

Kiro has no global hooks -- hooks must be injected per-agent into
~/.kiro/agents/<name>.json. Each agent gets 5 hook events.
"""

from __future__ import annotations

import sys
from pathlib import Path

KIRO_HOOK_EVENTS = ("agentSpawn", "userPromptSubmit", "preToolUse", "postToolUse", "stop")

# Parent of the observal_cli package directory
_PKG_ROOT = str(Path(__file__).resolve().parent.parent.parent)


def _python_cmd() -> str:
    """Return '{python}' or 'PYTHONPATH=... {python}' so observal_cli is always importable."""
    try:
        import importlib.util

        if importlib.util.find_spec("observal_cli") is not None:
            return sys.executable
    except Exception:
        pass
    if sys.platform == "win32":
        return f'set "PYTHONPATH={_PKG_ROOT}" && {sys.executable}'
    return f"PYTHONPATH={_PKG_ROOT} {sys.executable}"


def build_kiro_hook_cmd(hooks_url: str, agent_name: str, model: str = "") -> str:
    """Build the command string for the Kiro telemetry hook."""
    args = f"--url {hooks_url} --agent-name {agent_name}"
    if model:
        args += f" --model {model}"
    return f"{_python_cmd()} -m observal_cli.hooks.kiro_hook {args}"


def build_kiro_stop_cmd(hooks_url: str, agent_name: str, model: str = "") -> str:
    """Build the command string for the Kiro stop hook."""
    args = f"--url {hooks_url} --agent-name {agent_name}"
    if model:
        args += f" --model {model}"
    return f"{_python_cmd()} -m observal_cli.hooks.kiro_stop_hook {args}"


def build_kiro_hooks(hooks_url: str, agent_name: str, model: str = "") -> dict:
    """Build the complete hooks dict for a Kiro agent config."""
    cmd = build_kiro_hook_cmd(hooks_url, agent_name, model)
    stop = build_kiro_stop_cmd(hooks_url, agent_name, model)
    return {
        "agentSpawn": [{"command": cmd}],
        "userPromptSubmit": [{"command": cmd}],
        "preToolUse": [{"matcher": "*", "command": cmd}],
        "postToolUse": [{"matcher": "*", "command": cmd}],
        "stop": [{"command": stop}],
    }
