# SPDX-FileCopyrightText: 2026 Naraen Rammoorthi <naraen13@gmail.com>
# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""Compatibility entry point for Copilot CLI's shared session hook."""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

from observal_cli.hooks.session_push import main as _shared_main

if TYPE_CHECKING:
    from pathlib import Path


def main(home: Path | None = None) -> None:
    """Route existing installed hooks through durable acknowledged delivery."""
    _shared_main("copilot-cli", home=home)
    sys.stdout.write('{"continue":true}\n')
    sys.stdout.flush()


if __name__ == "__main__":
    main()
