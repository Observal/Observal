# SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""Optic: developer debug logging for Observal.

Configures loguru sinks. Call ``setup_optic()`` once at server startup.
Then use ``from loguru import logger as optic`` anywhere.

Architecture - every optic.* call flows through loguru into up to 3 sinks:

  1. stderr - INFO+ for the terminal / docker logs
  2. file   - TRACE+ for post-mortem (dev mode only, skipped if read-only FS)
  3. ring buffer - TRACE+ into memory, feeds the SSE /admin/logs/stream endpoint

The ring buffer is what makes ``observal logs --remote`` work.  Without it
a remote CLI user has zero visibility into a hosted instance.

Color policy:
  dev mode  -> stderr is always colored (for humans watching a terminal)
  prod mode -> stderr is never colored (ANSI codes break Loki/Datadog/CloudWatch)
  SSE/CLI   -> the CLI re-colorizes based on level (colors applied client-side)
"""

from __future__ import annotations

import sys
from pathlib import Path

from loguru import logger

# ---------------------------------------------------------------------------
# Ring buffer sink - bridges optic -> in-memory buffer -> SSE endpoint
# ---------------------------------------------------------------------------


_buffer_ref = None


def _ring_buffer_sink(message) -> None:
    """Loguru sink that feeds the in-memory ring buffer.

    Every log entry ends up here as a structured dict which the SSE endpoint
    polls and streams to remote CLI users.

    Audit records (logger.bind(audit=True)) are excluded because they fire on
    every HTTP request and would drown out operational logs. Audit data goes
    to the dedicated audit sink -> ClickHouse instead.
    """
    global _buffer_ref
    try:
        if _buffer_ref is None:
            from services.log_buffer import get_log_buffer

            _buffer_ref = get_log_buffer()

        record = message.record

        # Skip audit records (high-volume structured data, not operational logs)
        if record["extra"].get("audit"):
            return

        entry = {
            "timestamp": record["time"].strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
            "level": record["level"].name,
            "event": record["message"],
            "logger_name": record["name"],
            "function": record["function"],
            "line": record["line"],
        }
        if record["extra"]:
            entry["extra"] = dict(record["extra"])

        _buffer_ref.append(entry)
    except Exception:
        pass  # never break logging


# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------


def setup_optic(*, mode: str = "dev", level: str = "TRACE") -> None:
    """Configure loguru sinks.

    Args:
        mode: 'dev' = colored stderr + file + ring buffer.
              'prod' = plain stderr + ring buffer (no file, no colors).
        level: Floor for file sink and ring buffer (default TRACE).
               stderr always gets INFO+ regardless.
    """
    # Try to read the dynamic setting
    try:
        import services.dynamic_settings as ds

        fmt = ds.get_sync("observability.log_format")
        if fmt and ds._sync_cache_loaded:
            if fmt == "console":
                mode = "dev"
            elif fmt == "json":
                mode = "prod"
    except Exception:
        pass

    logger.remove()

    # ── Sink 1: stderr ───────────────────────────────────────────────────────

    if mode == "dev":
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
    else:
        # No colors - aggregators choke on ANSI escape codes
        logger.add(
            sys.stderr,
            level="INFO",
            colorize=False,
            format="{time:YYYY-MM-DDTHH:mm:ss.SSSZ} | {level:<7} | {name}:{function} - {message}",
        )

    # ── Sink 2: file (dev only) ─────────────────────────────────────────────

    if mode == "dev":
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
            pass  # read-only FS (Docker), skip gracefully

    # ── Sink 3: ring buffer (always, both modes) ────────────────────────────
    # This is the ONLY way TRACE/DEBUG logs are accessible in prod.

    logger.add(
        _ring_buffer_sink,
        level=level,
        format="{message}",  # structured fields extracted in the sink function
    )
