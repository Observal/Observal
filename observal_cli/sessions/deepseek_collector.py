# SPDX-FileCopyrightText: 2026 Observal contributors
# SPDX-License-Identifier: Apache-2.0

"""Host-side delivery invoked by the in-process DeepSeek Cordis plugin.

Unlike DeepSeek's command hooks this process runs outside the tool sandbox.
The plugin has already awaited the native session-persistence flush before
invoking a single-session collection. Reconciliation remains the recovery path
for a process killed before that boundary.
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

from loguru import logger as optic

from observal_cli.harness import SessionSource, ensure_loaded, get_adapter
from observal_cli.sessions.base import drain_session_source, load_config


def _collect(source: SessionSource) -> None:
    config = load_config()
    if not config:
        raise ValueError("Observal is not configured; run `observal auth login`")
    delivered = drain_session_source(
        source,
        config,
        hook_event="DeepSeekSessionFlush",
        final=False,
        spool_only=False,
        recover_from_server=False,
    )
    if not delivered:
        raise RuntimeError("session is queued locally but the Observal server did not acknowledge it")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Deliver persisted DeepSeek sessions to Observal")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--session-id")
    group.add_argument("--recover", action="store_true")
    parser.add_argument("--cwd", default="")
    options = parser.parse_args(argv)
    ensure_loaded()
    adapter = get_adapter("deepseek")
    try:
        if options.recover:
            # Never race a live session's flush. Only older sessions can have
            # been left behind by a previous invocation/crash.
            cutoff = datetime.now(UTC) - timedelta(minutes=2)
            for source in adapter.discover_session_sources(home=Path.home(), since_hours=168):
                if source.path.stat().st_mtime <= cutoff.timestamp():
                    _collect(source)
        else:
            source = adapter.resolve_session_source({"session_id": options.session_id, "cwd": options.cwd})
            if source is None:
                raise FileNotFoundError(f"DeepSeek session source not found: {options.session_id}")
            _collect(source)
    except Exception as exc:
        optic.warning("DeepSeek collection failed: {}", exc)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
