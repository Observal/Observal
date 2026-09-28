# SPDX-FileCopyrightText: 2026 Observal Contributors
# SPDX-License-Identifier: Apache-2.0

"""DeepSeek's Claude-compatible hooks, activated by the user Cordis patch."""

from __future__ import annotations

import re
import shlex
import sys
from pathlib import Path

EVENTS = ("PreToolUse", "PostToolUse", "Stop", "SessionStart", "UserPromptSubmit", "SubagentStop")
MODULE = "observal_cli.hooks.session_push"


def hook_command() -> str:
    """Return the local interpreter command invoked by the hooks plugin."""
    return f"{shlex.quote(sys.executable)} -m {MODULE} --harness deepseek"


def is_session_push_command(command: object) -> bool:
    """Recognize the generated Python module invocation, including older interpreters."""
    if not isinstance(command, str):
        return False
    try:
        argv = shlex.split(command)
    except ValueError:
        return False
    return (
        len(argv) == 5
        and re.fullmatch(r"python(?:3(?:\.\d+)?)?(?:\.exe)?", Path(argv[0]).name) is not None
        and argv[1:] == ["-m", MODULE, "--harness", "deepseek"]
    )


def build_hooks() -> dict:
    """Return the Claude-compatible hook rules accepted by dsh-hooks-claude-code."""
    command = hook_command()
    return {"hooks": {event: [{"hooks": [{"type": "command", "command": command}]}] for event in EVENTS}}
