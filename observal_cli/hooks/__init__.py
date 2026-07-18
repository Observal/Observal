# SPDX-FileCopyrightText: 2026 Subramania Raja <dhanpraja231@gmail.com>
# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""Hook runtime and spec interface.

This package contains:
- Shared Python session push runtime plus host-specific bridges
- Re-exports of hook spec helpers for convenience
"""

from observal_cli.harness_specs.claude_code_hooks_spec import (  # noqa: F401
    MANAGED_ENV_KEYS,
    get_desired_hooks,
)
from observal_cli.harness_specs.kiro_hooks_spec import build_kiro_hooks  # noqa: F401
