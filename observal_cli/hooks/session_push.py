# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""Generic Python harness hook entry point for durable session delivery."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from typing import TYPE_CHECKING

from loguru import logger as optic

from observal_cli.harness import ensure_loaded, get_adapter
from observal_cli.sessions.base import drain_session_source, load_config, log_error

if TYPE_CHECKING:
    from pathlib import Path

_FINAL_DELAY_SECONDS = 2.0
_STABLE_INTERVAL_SECONDS = 0.25
_STABLE_CHECKS = 2
_RECOVERY_MIN_AGE_SECONDS = 120


def main(home: Path | None = None, harness: str = "claude-code") -> None:
    """Read one hook payload from stdin without ever breaking the harness."""
    try:
        raw = sys.stdin.read()
        event = json.loads(raw)
        if isinstance(event, dict):
            _run_hook(event, harness=harness, home=home)
    except Exception as exc:
        optic.error("session push crashed (swallowed to protect harness): {}", exc)


def _run_hook(event: dict, *, harness: str, home: Path | None = None) -> None:
    ensure_loaded()
    adapter = get_adapter(harness)
    source = adapter.resolve_session_source(event, home=home)
    if source is None:
        optic.debug("{} hook did not resolve a session source", harness)
        return
    config = load_config(home=home)
    if config is None:
        optic.warning("no Observal config found - session source remains local")
        return

    hook_event = str(event.get("hook_event_name") or event.get("hookEventName") or event.get("event") or "")
    is_final = adapter.is_session_final(event)
    delivered = drain_session_source(
        source,
        config,
        hook_event=hook_event,
        final=False,
        extra_fields=adapter.session_extra_fields(source, event, is_final, home=home),
        home=home,
    )
    for related in adapter.related_session_sources(source, home=home):
        delivered = (
            drain_session_source(
                related,
                config,
                hook_event=hook_event,
                final=False,
                extra_fields=adapter.session_extra_fields(related, event, is_final, home=home),
                home=home,
            )
            and delivered
        )
    if not delivered:
        log_error(f"session_push: durable records pending for {harness} session {source.session_id}", home=home)

    if is_final:
        _spawn_worker(
            "--finalize-session",
            source.session_id,
            "--cwd",
            source.cwd,
            harness=harness,
        )
    else:
        _spawn_worker("--recover", "--exclude-session", source.session_id, harness=harness)


def _spawn_worker(*args: str, harness: str) -> None:
    try:
        subprocess.Popen(
            [sys.executable, "-m", "observal_cli.hooks.session_push", "--harness", harness, *args],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except Exception as exc:
        optic.trace("could not spawn {} session worker: {}", harness, exc)


def _wait_until_stable(path: Path) -> None:
    """Wait briefly for post-hook records to finish appending."""
    time.sleep(_FINAL_DELAY_SECONDS)
    stable = 0
    previous_size = -1
    while stable < _STABLE_CHECKS:
        try:
            size = path.stat().st_size
        except OSError:
            return
        stable = stable + 1 if size == previous_size else 0
        previous_size = size
        if stable < _STABLE_CHECKS:
            time.sleep(_STABLE_INTERVAL_SECONDS)


def _finalize_session(harness: str, session_id: str, cwd: str, home: Path | None = None) -> None:
    ensure_loaded()
    adapter = get_adapter(harness)
    source = adapter.resolve_session_source({"session_id": session_id, "cwd": cwd}, home=home)
    config = load_config(home=home)
    if source is None or config is None or source.path is None:
        return
    event = {"session_id": session_id, "cwd": cwd, "hook_event_name": "Stop"}
    _wait_until_stable(source.path)
    drain_session_source(
        source,
        config,
        hook_event="Stop",
        final=True,
        extra_fields=adapter.session_extra_fields(source, event, True, home=home),
        home=home,
    )
    for related in adapter.related_session_sources(source, home=home):
        if related.path is not None:
            _wait_until_stable(related.path)
        drain_session_source(
            related,
            config,
            hook_event="Stop",
            final=True,
            extra_fields=adapter.session_extra_fields(related, event, True, home=home),
            home=home,
        )


def _recover_sessions(harness: str, exclude_session: str = "", home: Path | None = None) -> None:
    ensure_loaded()
    adapter = get_adapter(harness)
    config = load_config(home=home)
    if config is None:
        return
    now = time.time()
    for source in adapter.discover_session_sources(home=home):
        if source.session_id == exclude_session or source.path is None:
            continue
        try:
            if now - source.path.stat().st_mtime < _RECOVERY_MIN_AGE_SECONDS:
                continue
        except OSError:
            continue
        event = {"session_id": source.session_id, "hook_event_name": "Stop"}
        drain_session_source(
            source,
            config,
            hook_event="CrashRecovery",
            final=True,
            extra_fields=adapter.session_extra_fields(source, event, True, home=home),
            home=home,
        )


def cli_main() -> None:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--harness", default="claude-code")
    parser.add_argument("--finalize-session", default="")
    parser.add_argument("--cwd", default="")
    parser.add_argument("--recover", action="store_true")
    parser.add_argument("--exclude-session", default="")
    args = parser.parse_args()
    try:
        if args.finalize_session:
            _finalize_session(args.harness, args.finalize_session, args.cwd)
        elif args.recover:
            _recover_sessions(args.harness, args.exclude_session)
        else:
            main(harness=args.harness)
    except Exception as exc:
        optic.error("session worker crashed: {}", exc)


if __name__ == "__main__":
    cli_main()
