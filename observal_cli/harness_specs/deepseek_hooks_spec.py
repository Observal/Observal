# SPDX-FileCopyrightText: 2026 Observal Contributors
# SPDX-License-Identifier: Apache-2.0

"""Recognize obsolete DeepSeek command hooks without executing foreign rules."""

from __future__ import annotations

import re
import shlex
from pathlib import Path

EVENTS = ("PreToolUse", "PostToolUse", "Stop", "SessionStart", "UserPromptSubmit", "SubagentStop")
MODULE = "observal_cli.hooks.session_push"


def is_session_push_command(command: object) -> bool:
    """Recognize earlier Observal telemetry commands so upgrades remove them."""
    if not isinstance(command, str):
        return False
    try:
        argv = shlex.split(command)
    except ValueError:
        return False
    return (
        len(argv) in (5, 7)
        and re.fullmatch(r"python(?:3(?:\.\d+)?)?(?:\.exe)?", Path(argv[0]).name) is not None
        and argv[1:5] == ["-m", MODULE, "--harness", "deepseek"]
        and (len(argv) == 5 or (argv[5] == "--dsh-home" and Path(argv[6]).is_absolute()))
    )
