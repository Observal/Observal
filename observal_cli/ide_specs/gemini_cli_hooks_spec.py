# SPDX-FileCopyrightText: 2026 Madhumidha
# SPDX-FileCopyrightText: 2026 Madhumidha <madhumidha072005@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Declarative hook specification for Gemini CLI settings.

Defines the desired state of Observal-managed hooks for Gemini CLI.
The reconciler compares this against ~/.gemini/settings.json.
"""

from __future__ import annotations

import sys
from pathlib import Path

from observal_cli.shared.utils import OBSERVAL_METADATA_KEY

HOOKS_SPEC_VERSION = "1"
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


def get_desired_hooks() -> dict[str, list[dict]]:
    """Return the desired hooks spec for Gemini CLI.

    Injects a command hook into BeforeAgent and SessionEnd.
    """
    meta = {OBSERVAL_METADATA_KEY: {"version": HOOKS_SPEC_VERSION}}
    cmd = f"{_python_cmd()} -m observal_cli.hooks.session_push"

    hook_group: list[dict] = [{**meta, "hooks": [{"type": "command", "command": cmd}]}]

    return {
        "BeforeAgent": hook_group,
        "SessionEnd": hook_group,
    }
