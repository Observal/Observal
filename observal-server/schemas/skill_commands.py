# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-FileCopyrightText: 2026 tsitu0 <tomsitu0102@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

from __future__ import annotations

import re

SLASH_COMMAND_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


def normalize_slash_command(value: str | None) -> str | None:
    """Return a canonical slash command name, or raise for unsafe values."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("slash_command must be a string")

    if value == "":
        return None
    command = value
    if command.startswith("/"):
        command = command[1:]
    if not SLASH_COMMAND_RE.fullmatch(command):
        raise ValueError("slash_command must match ^[a-z0-9][a-z0-9_-]{0,63}$")
    return command
