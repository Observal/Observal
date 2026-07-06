# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""Ensures all harness adapter modules are imported, triggering registration."""

from observal_cli.harness import antigravity as _antigravity  # noqa: F401
from observal_cli.harness import claude_code as _claude_code  # noqa: F401
from observal_cli.harness import codex as _codex  # noqa: F401
from observal_cli.harness import copilot as _copilot  # noqa: F401
from observal_cli.harness import copilot_cli as _copilot_cli  # noqa: F401
from observal_cli.harness import cursor as _cursor  # noqa: F401
from observal_cli.harness import kiro as _kiro  # noqa: F401
from observal_cli.harness import opencode as _opencode  # noqa: F401
from observal_cli.harness import pi as _pi  # noqa: F401
