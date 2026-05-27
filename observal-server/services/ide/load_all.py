# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Load all IDE adapters.

Import this module to ensure all adapters are registered in the registry.
Each adapter module auto-registers itself on import.
"""

from services.ide import claude_code as _claude_code  # noqa: F401
from services.ide import codex as _codex  # noqa: F401
from services.ide import copilot as _copilot  # noqa: F401
from services.ide import copilot_cli as _copilot_cli  # noqa: F401
from services.ide import cursor as _cursor  # noqa: F401
from services.ide import gemini_cli as _gemini_cli  # noqa: F401
from services.ide import kiro as _kiro  # noqa: F401
from services.ide import opencode as _opencode  # noqa: F401
from services.ide import pi as _pi  # noqa: F401
