"""Declarative hook specification for Claude Code settings.

Defines the desired state of Observal-managed hooks. The reconciler
compares this spec against the user's current ~/.claude/settings.json
and applies non-destructive updates.

Session JSONL strategy: only 2 events are needed (UserPromptSubmit + Stop)
since we read the JSONL file incrementally rather than parsing individual
hook events.

Bump HOOKS_SPEC_VERSION whenever the hook definitions change.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Bump this when hook definitions change.
HOOKS_SPEC_VERSION = "10"

# Metadata key injected into every Observal matcher group.
OBSERVAL_METADATA_KEY = "_observal"

# Parent of the observal_cli package directory
_PKG_ROOT = str(Path(__file__).resolve().parent.parent.parent)

# Legacy marker substrings used to detect old-style hooks for cleanup.
_LEGACY_HOOK_MARKERS = (
    "observal-hook",
    "observal-stop-hook",
    "/api/v1/otel/hooks",
    "/api/v1/telemetry/hooks",
    "observal_cli.hooks.kiro_hook",
    "observal_cli.hooks.kiro_stop_hook",
    "observal_cli.hooks.gemini_hook",
    "observal_cli.hooks.gemini_stop_hook",
    "observal_cli.hooks.copilot_cli_hook",
    "observal_cli.hooks.copilot_cli_stop_hook",
    "observal_cli.hooks.buffer_event",
    "observal_cli.hooks.flush_buffer",
)


def is_observal_hook_entry(hook_entry: dict) -> bool:
    """Return True if a single hook handler dict belongs to Observal."""
    cmd = hook_entry.get("command", "")
    url = hook_entry.get("url", "")
    return any(m in cmd or m in url for m in _LEGACY_HOOK_MARKERS) or "observal_cli.hooks.session_push" in cmd


def is_observal_matcher_group(matcher_group: dict) -> bool:
    """Return True if a matcher group is Observal-managed."""
    if OBSERVAL_METADATA_KEY in matcher_group:
        return True
    return any(is_observal_hook_entry(h) for h in matcher_group.get("hooks", []))


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


def get_desired_hooks() -> dict[str, list[dict]]:
    """Return the desired hooks spec for Claude Code settings.

    Only 2 events: UserPromptSubmit and Stop.  Both invoke the session
    push hook which reads the JSONL file incrementally.
    """
    meta = {OBSERVAL_METADATA_KEY: {"version": HOOKS_SPEC_VERSION}}
    cmd = f"{_python_cmd()} -m observal_cli.hooks.session_push"

    hook_group: list[dict] = [{**meta, "hooks": [{"type": "command", "command": cmd}]}]

    return {
        "UserPromptSubmit": hook_group,
        "Stop": hook_group,
    }


def get_desired_env(*_args, **_kwargs) -> dict[str, str]:
    """Legacy stub — no env vars needed for session JSONL push.

    Old callers pass (server_url, hooks_token, ...) — ignored.
    Config now lives in ~/.observal/config.json.
    """
    return {}


# Keys in settings.env that Observal manages (for cleanup).
MANAGED_ENV_KEYS = frozenset(
    {
        "CLAUDE_CODE_ENABLE_TELEMETRY",
        "OTEL_METRICS_EXPORTER",
        "OTEL_LOGS_EXPORTER",
        "OTEL_EXPORTER_OTLP_PROTOCOL",
        "OTEL_EXPORTER_OTLP_HEADERS",
        "OTEL_EXPORTER_OTLP_ENDPOINT",
        "OTEL_RESOURCE_ATTRIBUTES",
        "OBSERVAL_HOOKS_URL",
        "OBSERVAL_HOOKS_SPEC_VERSION",
        "OBSERVAL_USER_ID",
        "OBSERVAL_USERNAME",
        "OBSERVAL_AGENT_NAME",
    }
)
