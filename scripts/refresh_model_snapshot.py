#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Aryan Iyappan <aryaniyappan2006@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Refresh the vendored model catalog snapshot from models.dev.

This is a manual ops tool — run it during a release if you want the offline
floor (used when ``models.dev`` is unreachable) to track upstream. The live
server does NOT call this script; it always tries the network first and falls
back to whatever this snapshot contained at build time.

Usage:
    python scripts/refresh_model_snapshot.py [--out PATH]
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

UPSTREAM_URL = "https://models.dev/api.json"
DEFAULT_OUT = Path(__file__).resolve().parent.parent / "observal-server" / "data" / "model_registry_seed.json"
KEEP_PROVIDERS = {"anthropic", "openai", "google", "google-vertex"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="Output path (default: vendored seed)")
    parser.add_argument(
        "--all-providers",
        action="store_true",
        help="Keep every provider models.dev returns (default keeps only the IDE-mapped ones).",
    )
    args = parser.parse_args()

    print(f"Fetching {UPSTREAM_URL}...")
    try:
        with urllib.request.urlopen(UPSTREAM_URL, timeout=20) as resp:
            data = json.load(resp)
    except (urllib.error.URLError, json.JSONDecodeError, OSError) as e:
        print(f"Fetch failed: {e}", file=sys.stderr)
        return 1

    if not args.all_providers:
        data = {pid: pdata for pid, pdata in data.items() if pid in KEEP_PROVIDERS}

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, sort_keys=True)
    total = sum(len(p.get("models", {})) for p in data.values() if isinstance(p, dict))
    print(f"Wrote {args.out} ({total} models across {len(data)} providers).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
