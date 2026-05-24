# SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Optic: developer debug logging for Observal.

Configures loguru sinks based on log format setting. Call ``setup_optic()``
once at server startup. Then use ``from loguru import logger`` anywhere
in the codebase to log actions.

Terminal (stderr) gets INFO+ only to keep output clean.
File (~/.observal/logs/dev.log) gets full DEBUG trace in console mode.
Production gets INFO+ with plain formatting (no colors).

The log format is determined by:
1. The ``observability.log_format`` dynamic setting (if the sync cache is loaded)
2. Otherwise, derived from license key presence (no license = console, licensed = json)

Changing the setting requires a server restart to take effect.
"""

from __future__ import annotations

import sys
from pathlib import Path

from loguru import logger


def setup_optic(*, mode: str = "local", level: str = "DEBUG") -> None:
    """Configure loguru sinks based on log format.

    Args:
        mode: Fallback mode when dynamic setting is unavailable.
              'local' = colorized console + debug file.
              'enterprise' = plain JSON to stderr.
        level: Minimum log level for file sink (default: DEBUG).
    """
    # Try to read the dynamic setting (sync cache may be loaded already)
    try:
        import services.dynamic_settings as ds

        fmt = ds.get_sync("observability.log_format")
        if fmt == "console":
            mode = "local"
        elif fmt == "json":
            mode = "enterprise"
    except Exception:
        pass

    # Remove loguru's default stderr sink
    logger.remove()

    if mode == "local":
        # Console: INFO+ only to avoid clogging the terminal
        logger.add(
            sys.stderr,
            level="INFO",
            colorize=True,
            format=(
                "<green>{time:HH:mm:ss.SSS}</green> | "
                "<level>{level:<7}</level> | "
                "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
                "<level>{message}</level>"
            ),
        )
        # File: full DEBUG trace for post-mortem debugging
        # Skip gracefully if home dir is read-only (e.g. Docker containers)
        try:
            log_path = Path.home() / ".observal" / "logs" / "dev.log"
            log_path.parent.mkdir(parents=True, exist_ok=True)
            logger.add(
                str(log_path),
                rotation="10 MB",
                retention=5,
                level=level,
                format=("{time:YYYY-MM-DD HH:mm:ss.SSS} | {level:<7} | {name}:{function}:{line} - {message}"),
            )
        except OSError:
            pass
    else:
        # Production: INFO+ to stderr, plain format (JSON handled by structlog)
        logger.add(
            sys.stderr,
            level="INFO",
            colorize=False,
            format="{time:YYYY-MM-DDTHH:mm:ss.SSSZ} | {level:<7} | {name}:{function} - {message}",
        )
