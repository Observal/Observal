# SPDX-FileCopyrightText: 2026 Riya Rani <rr1182764@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""
Declarative spec for Observal-managed hook entries in ~/.gemini/settings.json.

This module describes the hooks that Observal installs into Gemini CLI's settings
file, following the same pattern used for Claude Code, Kiro, and Cursor.

Hook command: python -m observal_cli.hooks.gemini_session_push
"""

from __future__ import annotations

# Bump this when the shape of any hook entry changes so the reconciler / doctor
# can detect stale entries left behind by older Observal versions.
GEMINI_HOOKS_SPEC_VERSION = "1.0.0"

# Identifier prefix embedded in every hook entry so is_observal_hook_entry()
# can reliably distinguish Observal-managed hooks from user-defined ones.
_OBSERVAL_MARKER = "observal"

# The module that handles Gemini session telemetry.
_PUSH_MODULE = "observal_cli.hooks.gemini_session_push"

# Gemini CLI hook event names (sourced from the Gemini CLI research spike).
_GEMINI_HOOK_EVENTS: tuple[str, ...] = (
    "sessionStart",
    "sessionEnd",
    "toolCallStart",
    "toolCallEnd",
)


def build_gemini_hooks() -> list[dict]:
    """Return the list of Observal-managed hook entries for ~/.gemini/settings.json.

    The returned list is ready to be merged into (or compared against) the
    ``hooks`` array inside the Gemini settings JSON.  Each entry follows the
    schema Gemini CLI expects::

        {
            "name": "<string>",
            "event": "<gemini-event-name>",
            "command": "python -m observal_cli.hooks.gemini_session_push",
            "enabled": true
        }

    Returns
    -------
    list[dict]
        One dict per supported Gemini hook event.
    """
    return [
        {
            "name": f"{_OBSERVAL_MARKER}_{event}",
            "event": event,
            "command": f"python -m {_PUSH_MODULE}",
            "enabled": True,
        }
        for event in _GEMINI_HOOK_EVENTS
    ]


def is_observal_hook_entry(entry: dict) -> bool:
    """Return True if *entry* was created by Observal and is safe to manage.

    Used by the reconciler (to decide whether to update an entry) and by the
    doctor cleanup (to decide whether to remove an orphaned entry).

    Parameters
    ----------
    entry:
        A single item from the ``hooks`` list inside ``~/.gemini/settings.json``.

    Returns
    -------
    bool
        ``True`` when the entry's ``name`` starts with the Observal marker
        **and** its ``command`` references the Observal push module.
    """
    if not isinstance(entry, dict):
        return False
    name: str = entry.get("name", "")
    command: str = entry.get("command", "")
    return name.startswith(_OBSERVAL_MARKER) and _PUSH_MODULE in command
