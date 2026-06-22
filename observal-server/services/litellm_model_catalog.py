# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Read the vendored LiteLLM model catalog snapshot."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from schemas.insights_models import LiteLLMModel, LiteLLMProvider

SNAPSHOT_PATH = Path(__file__).resolve().parent.parent / "data" / "litellm_model_catalog.json"
INSIGHTS_MODES = {"chat", "responses"}


@lru_cache(maxsize=1)
def _insights_models() -> tuple[LiteLLMModel, ...]:
    payload = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
    models = [LiteLLMModel.model_validate(row) for row in payload["models"] if row.get("mode") in INSIGHTS_MODES]
    models.sort(key=lambda model: (model.litellm_provider, model.model_id))
    return tuple(models)


def _label(provider: str) -> str:
    return provider.replace("_", " ").title()


def list_providers() -> list[LiteLLMProvider]:
    counts: dict[str, int] = {}
    for model in _insights_models():
        counts[model.litellm_provider] = counts.get(model.litellm_provider, 0) + 1
    return [
        LiteLLMProvider(id=provider, label=_label(provider), model_count=count)
        for provider, count in sorted(counts.items())
    ]


def list_models(provider: str) -> list[LiteLLMModel]:
    return [model for model in _insights_models() if model.litellm_provider == provider]
