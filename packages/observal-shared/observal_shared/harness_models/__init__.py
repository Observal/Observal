# SPDX-License-Identifier: AGPL-3.0-only
from __future__ import annotations

import json
from functools import lru_cache
from importlib.resources import files


@lru_cache(maxsize=1)
def all_harness_models() -> dict[str, dict]:
    data = {}
    for item in files(__name__).iterdir():
        if item.name.endswith('.json'):
            payload = json.loads(item.read_text())
            data[payload['harness']] = payload
    return data


def harness_models(harness: str) -> dict:
    return all_harness_models()[harness]


def supported_model_ids(harness: str) -> list[str]:
    return [row['id'] for row in harness_models(harness).get('models', [])]
