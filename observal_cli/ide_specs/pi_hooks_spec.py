# SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Hook specification for Pi.

Pi uses in-process extensions for session telemetry, not command-based hooks.
This module provides metadata for `observal doctor patch` to display guidance.
"""

from __future__ import annotations


def build_hooks() -> dict:
    """Return hook metadata for Pi.

    Pi's hooks are delivered as the observal-pi npm package.
    There is no settings.json injection - users install via `pi install`.
    """
    return {
        "hook_type": "extension",
        "install_command": "pi install npm:observal-pi",
        "package": "observal-pi",
    }
