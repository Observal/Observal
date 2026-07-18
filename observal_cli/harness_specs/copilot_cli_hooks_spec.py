# SPDX-FileCopyrightText: 2026 Naraen Rammoorthi <naraen13@gmail.com>
# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""Copilot CLI hook specification for session telemetry.

Copilot CLI hooks live at ~/.copilot/hooks/*.json (user-level) or
.github/hooks/*.json (project-level). Each file is a JSON object with
version and hooks keys. Hooks receive JSON on stdin and fire synchronously.

Events: sessionStart, sessionEnd, userPromptSubmitted, preToolUse, postToolUse.
"""

from __future__ import annotations

import sys
from pathlib import Path

COPILOT_CLI_HOOK_EVENTS = (
    "sessionStart",
    "sessionEnd",
    "userPromptSubmitted",
    "preToolUse",
    "postToolUse",
)

# Parent of the observal_cli package directory
_PKG_ROOT = str(Path(__file__).resolve().parent.parent.parent)


def _python_cmd() -> str:
    """Return python command with PYTHONPATH set if needed.

    Quotes the path to handle spaces in directory names.
    """
    try:
        import importlib.util

        if importlib.util.find_spec("observal_cli") is not None:
            # Quote to handle spaces in paths
            return f'"{sys.executable}"'
    except Exception:
        pass
    if sys.platform == "win32":
        return f'set "PYTHONPATH={_PKG_ROOT}" && "{sys.executable}"'
    return f'PYTHONPATH="{_PKG_ROOT}" "{sys.executable}"'


def build_copilot_cli_hooks(agent_id: str = "") -> dict:
    """Return the complete hook file content for Copilot CLI.

    Produces a JSON-serializable dict matching the Copilot CLI hook file
    format: {"version": 1, "hooks": {"eventName": [{"type": "command", "bash": "...", "timeoutSec": 5}]}}

    Includes powershell key for Windows environments where Copilot CLI
    executes hooks via PowerShell rather than bash.

    When *agent_id* is supplied, ``OBSERVAL_AGENT_ID`` is prepended to both
    command forms so the session push hook can attribute events to a specific
    agent+version via the lockfile. This mirrors the per-agent attribution
    Kiro gets from build_kiro_hooks(). Copilot CLI project hooks live in
    ``.github/hooks/observal.json`` (one file per project), so the UUID
    identifies whichever agent was pulled into that project.
    """
    module = "observal_cli.hooks.copilot_cli_session_push"
    bash_cmd = f"{_python_cmd()} -m {module}"
    # PowerShell command uses bare 'python' which must be on Windows PATH
    ps_cmd = f"python -m {module}"

    if agent_id:
        if sys.platform == "win32":
            bash_cmd = f'set "OBSERVAL_AGENT_ID={agent_id}" && {bash_cmd}'
        else:
            bash_cmd = f"OBSERVAL_AGENT_ID={agent_id} {bash_cmd}"
        # PowerShell (used on Windows) sets the env var in-process for the child.
        ps_cmd = f"$env:OBSERVAL_AGENT_ID='{agent_id}'; {ps_cmd}"

    hooks: dict[str, list[dict]] = {}
    for event in COPILOT_CLI_HOOK_EVENTS:
        hooks[event] = [{"type": "command", "bash": bash_cmd, "powershell": ps_cmd, "timeoutSec": 5}]
    return {"version": 1, "hooks": hooks}
