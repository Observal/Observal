# SPDX-License-Identifier: AGPL-3.0-only
"""Shared harness model catalog loader."""

from __future__ import annotations

import json
from functools import lru_cache
from importlib.resources import files

PACKAGE = "observal_shared.harness_models"


@lru_cache(maxsize=1)
def all_harness_models() -> dict[str, dict]:
    root = files(PACKAGE)
    data: dict[str, dict] = {}
    for item in root.iterdir():
        if item.name.endswith(".json"):
            payload = json.loads(item.read_text())
            data[payload["harness"]] = payload
    return data


def harness_models(harness: str) -> dict:
    return all_harness_models()[harness]


def supported_model_ids(harness: str) -> list[str]:
    return [row["id"] for row in harness_models(harness).get("models", [])]


def supports_model(harness: str, model: str) -> bool:
    if not model:
        return True
    for row in harness_models(harness).get("models", []):
        mid = row["id"]
        if row.get("kind") == "provider_source":
            prefix = mid.split("<", 1)[0]
            if prefix and model.startswith(prefix):
                return True
        elif model == mid:
            return True
    return False
