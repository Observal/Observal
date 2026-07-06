# SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""Optic: developer debug logging for the Observal CLI.

Call ``setup_optic()`` once in the CLI main callback.
Then use ``from loguru import logger as optic`` in any module.

Flags:
  (none)    → silent (loguru no-ops)
  --verbose → INFO+ to stderr
  --debug   → DEBUG+ to stderr + file
  --trace   → TRACE+ to stderr + file (maximum granularity)
"""

from __future__ import annotations

import sys
from pathlib import Path

from loguru import logger


def setup_optic(*, trace: bool = False, debug: bool = False, verbose: bool = False) -> None:
    """Configure loguru sinks for CLI.

    Args:
        trace: TRACE+ to stderr + file.  Maximum detail.
        debug: DEBUG+ to stderr + file.
        verbose: INFO+ to stderr only.
    """
    logger.remove()

    level = "TRACE" if trace else "DEBUG" if debug else "INFO" if verbose else None

    if level is None:
        return  # silent

    logger.add(
        sys.stderr,
        level=level,
        colorize=True,
        format=(
            "<green>{time:HH:mm:ss.SSS}</green> | "
            "<level>{level:<7}</level> | "
            "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
            "<level>{message}</level>"
        ),
    )

    if trace or debug:
        log_path = Path.home() / ".observal" / "logs" / "cli.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        logger.add(
            str(log_path),
            rotation="10 MB",
            retention=5,
            level="TRACE" if trace else "DEBUG",
            format=("{time:YYYY-MM-DD HH:mm:ss.SSS} | {level:<7} | {name}:{function}:{line} - {message}"),
        )
