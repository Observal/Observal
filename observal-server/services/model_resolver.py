# SPDX-License-Identifier: AGPL-3.0-only
"""Resolve the model value a harness config should emit."""

from __future__ import annotations

from schemas.harness_registry import HARNESS_REGISTRY, has_model_selection


def _format_for_harness(model: str, provider: str, harness: str) -> str:
    if harness == "claude-code":
        lowered = model.lower()
        for alias in ("opus", "sonnet", "haiku"):
            if alias in lowered:
                return alias
    if harness == "opencode":
        return model if "/" in model else f"{provider}/{model}"
    return model


def _candidate_for_harness(harness: str, models_by_harness: dict | None, model_name: str | None) -> str | None:
    if models_by_harness and models_by_harness.get(harness):
        return models_by_harness[harness]
    if harness == "claude-code" and model_name:
        return model_name
    return None


def _provider_for(harness: str, model: str) -> str:
    for row_id in HARNESS_REGISTRY[harness].get("supported_models", []):
        if row_id == model:
            if model.startswith("opencode/"):
                return "opencode"
            if model.startswith("gemini"):
                return "google"
            if model.startswith("gpt"):
                return "openai"
            if model.startswith("claude") or model in {"sonnet", "opus", "haiku", "fable", "best", "default"}:
                return "anthropic"
    return "anthropic"


def _supported(harness: str, candidate: str) -> bool:
    rows = HARNESS_REGISTRY[harness].get("supported_models", [])
    if candidate in rows:
        return True
    return any("<" in row and candidate.startswith(row.split("<", 1)[0]) for row in rows)


def resolve_saved_value(harness: str, model_name: str, models_by_harness: dict | None) -> str | None:
    if not has_model_selection(harness):
        return None
    candidate = _candidate_for_harness(harness, models_by_harness, model_name)
    if not candidate:
        return None
    return _format_for_harness(candidate, _provider_for(harness, candidate), harness)


async def resolve_model_for_harness(
    harness: str,
    *,
    model_name: str = "",
    models_by_harness: dict | None = None,
    override: str | None = None,
) -> tuple[str | None, list[str]]:
    warnings: list[str] = []
    if not has_model_selection(harness):
        if override:
            warnings.append(f"{harness} does not accept a model choice; ignoring --model {override}.")
        return None, warnings
    candidate = override or _candidate_for_harness(harness, models_by_harness, model_name)
    if not candidate or candidate == "inherit":
        return None, warnings
    if not _supported(harness, candidate):
        warnings.append(f"Model '{candidate}' is not in the {harness} harness registry. Falling back to auto/default.")
        return None, warnings
    return _format_for_harness(candidate, _provider_for(harness, candidate), harness), warnings
