# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""Antigravity hook bridge to shared durable acknowledged session delivery."""

from __future__ import annotations

import json
import sys
from typing import TYPE_CHECKING

from observal_cli.hooks.session_push import _run_hook
from observal_cli.sessions.antigravity import resolve_hook_event, resolve_transcript_path

if TYPE_CHECKING:
    from pathlib import Path


def main(home: Path | None = None) -> None:
    """Run shared delivery and always return the JSON response agy requires."""
    event: dict = {}
    try:
        parsed = json.loads(sys.stdin.read())
        if isinstance(parsed, dict):
            event = parsed
            _run_hook(event, harness="antigravity", home=home)
    except Exception:
        pass
    finally:
        sys.stdout.write(json.dumps(_hook_response(resolve_hook_event(event, home=home))))
        sys.stdout.flush()


def _hook_response(hook_event: str) -> dict:
    """Allow normal termination for Antigravity Stop hooks."""
    if hook_event.lower() in {"session_end", "sessionend", "stop"}:
        return {"decision": ""}
    return {}


def _resolve_path_for_platform(path_str: str) -> str:
    """Compatibility wrapper for existing callers and installed tests."""
    return str(resolve_transcript_path(path_str)) if path_str else path_str


if __name__ == "__main__":
    main()
