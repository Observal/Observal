# SPDX-FileCopyrightText: 2026 Riya Rani <rr1182764@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""
Declarative spec for Observal-managed hook entries in Cursor's config.

This module mirrors the pattern established by:
  - claude_code_hooks_spec.py  (closest pattern)
  - kiro_hooks_spec.py         (simpler variant)

The ``observal doctor patch --ide cursor`` command uses this spec to
reconcile Cursor's ``~/.cursor/mcp.json`` (rules/hooks section) so that
the four lifecycle events always run the Observal session-push command.
"""

from __future__ import annotations

from typing import Any

# ---------------------------------------------------------------------------
# Version - bump whenever the desired hook shape changes so that the
# reconciler knows it must re-patch even if an entry is already present.
# ---------------------------------------------------------------------------
CURSOR_HOOKS_SPEC_VERSION: str = "1.0.0"

# ---------------------------------------------------------------------------
# The canonical command that every Cursor hook must invoke.
# Depends on the hook module introduced in issue #829.
# ---------------------------------------------------------------------------
_OBSERVAL_HOOK_COMMAND: str = "python -m observal_cli.hooks.cursor_session_push"

# Legacy command path kept for backwards-compat detection (pre-#829 layout).
_OBSERVAL_HOOK_COMMAND_LEGACY: str = "python -m observal_cli.cursor_session_push"

# Cursor fires these four lifecycle events that Observal cares about.
_HOOK_EVENTS: tuple[str, ...] = (
    "UserPromptSubmit",
    "Stop",
    "PreToolUse",
    "PostToolUse",
)

# The matcher group name Observal uses so entries can be identified / cleaned.
_OBSERVAL_MATCHER_GROUP: str = "observal"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_desired_hooks() -> dict[str, Any]:
    """Return the full hook configuration dict in Cursor's expected schema.

    Cursor's hooks config is a mapping of event names to lists of hook
    objects.  Each hook object has at minimum::

        {
            "matcher": "<group-name>",
            "hooks": [
                {"type": "command", "command": "<shell command>"}
            ]
        }

    Returns
    -------
    dict[str, Any]
        Ready-to-merge hook configuration keyed by lifecycle event name.
    """
    hook_entry = _build_hook_entry()
    return {event: [hook_entry] for event in _HOOK_EVENTS}


# Alias for consistency with the build_* naming found in kiro_hooks_spec.py
def build_cursor_hooks() -> dict[str, Any]:
    """Alias for :func:`get_desired_hooks`."""
    return get_desired_hooks()


def is_observal_hook_entry(entry: dict[str, Any]) -> bool:
    """Return ``True`` if *entry* was written by Observal.

    Recognises both the current canonical command path and the legacy path
    so that old entries are cleaned up correctly by ``doctor patch``.

    Parameters
    ----------
    entry:
        A single hook object from Cursor's config.
    """
    if not isinstance(entry, dict):
        return False

    # Check the matcher group first (fast path).
    if is_observal_matcher_group(entry):
        return True

    # Fall back to inspecting the command string inside nested hooks.
    for hook in entry.get("hooks", []):
        cmd = hook.get("command", "")
        if _is_observal_command(cmd):
            return True

    # Also handle flat {"command": "..."} entries (Cursor compact format).
    flat_cmd = entry.get("command", "")
    return bool(flat_cmd and _is_observal_command(flat_cmd))


def is_observal_matcher_group(entry: dict[str, Any]) -> bool:
    """Return ``True`` if *entry* carries the Observal matcher group label.

    Parameters
    ----------
    entry:
        A single hook object from Cursor's config.
    """
    if not isinstance(entry, dict):
        return False
    return entry.get("matcher", "").lower() == _OBSERVAL_MATCHER_GROUP.lower()


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _build_hook_entry() -> dict[str, Any]:
    """Build the canonical Observal hook object for Cursor."""
    return {
        "matcher": _OBSERVAL_MATCHER_GROUP,
        "hooks": [
            {
                "type": "command",
                "command": _OBSERVAL_HOOK_COMMAND,
            }
        ],
    }


def _is_observal_command(command: str) -> bool:
    """Return ``True`` if *command* is a known Observal push command."""
    return command.strip() in {
        _OBSERVAL_HOOK_COMMAND,
        _OBSERVAL_HOOK_COMMAND_LEGACY,
    }
