# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Ensures all IDE adapter modules are imported, triggering registration."""

from observal_cli.ide import claude_code as _claude_code  # noqa: F401
from observal_cli.ide import codex as _codex  # noqa: F401
from observal_cli.ide import copilot as _copilot  # noqa: F401
from observal_cli.ide import copilot_cli as _copilot_cli  # noqa: F401
from observal_cli.ide import cursor as _cursor  # noqa: F401
from observal_cli.ide import gemini_cli as _gemini_cli  # noqa: F401
from observal_cli.ide import kiro as _kiro  # noqa: F401
from observal_cli.ide import opencode as _opencode  # noqa: F401
from observal_cli.ide import vscode as _vscode  # noqa: F401
