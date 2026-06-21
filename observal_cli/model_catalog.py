# SPDX-License-Identifier: AGPL-3.0-only
"""Registry-backed harness model catalog for the CLI."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / "packages/observal-shared/observal_shared/harness_models"


def _load(harness: str) -> dict:
    return json.loads((ROOT / f"{harness}.json").read_text())


def fetch_catalog(*, refresh: bool = False, harness: str | None = None, ttl: int = 0) -> dict:
    del refresh, ttl
    files = [ROOT / f"{harness}.json"] if harness else sorted(ROOT.glob("*.json"))
    rows = []
    for path in files:
        data = json.loads(path.read_text())
        for row in data.get("models", []):
            rows.append({**row, "harness": data["harness"], "model_id": row["id"], "display_name": row.get("label", row["id"])})
    return {"models": rows, "source": "harness-registry", "degraded": False}


def model_choices_for_picker(catalog: dict, harness: str) -> list[tuple[str, str]]:
    return [
        (m["model_id"], m.get("display_name") or m["model_id"])
        for m in catalog.get("models", [])
        if m.get("harness") == harness and m.get("kind") != "provider_source"
    ]


def invalidate_cache() -> None:
    return None
