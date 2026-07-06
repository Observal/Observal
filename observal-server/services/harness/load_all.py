# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""Load all harness adapters.

Import this module to ensure all adapters are registered in the registry.
Each adapter module auto-registers itself on import.
"""

from services.harness import antigravity as _antigravity  # noqa: F401
from services.harness import claude_code as _claude_code  # noqa: F401
from services.harness import codex as _codex  # noqa: F401
from services.harness import copilot as _copilot  # noqa: F401
from services.harness import copilot_cli as _copilot_cli  # noqa: F401
from services.harness import cursor as _cursor  # noqa: F401
from services.harness import kiro as _kiro  # noqa: F401
from services.harness import opencode as _opencode  # noqa: F401
from services.harness import pi as _pi  # noqa: F401
