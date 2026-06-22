# SPDX-FileCopyrightText: 2026 Aryan Iyappan <aryaniyappan2006@gmail.com>
# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Resolve the model value a harness config should emit."""

from __future__ import annotations

import re

from schemas.harness_registry import HARNESS_REGISTRY, has_model_selection

# Pre-compiled pattern: claude-<family>-<major>-<minor><optional-date-suffix>
# All digit groups are bounded to prevent polynomial backtracking on adversarial input.
_KIRO_MODEL_RE = re.compile(r"^(claude-[a-z]+-\d{1,3})-(\d{1,3})(-\d{8})?$")


def _format_for_harness(model: str, provider: str, harness: str) -> str:
    if harness == "claude-code":
        lowered = model.lower()
        for alias in ("opus", "sonnet", "haiku"):
            if alias in lowered:
                return alias
    if harness == "opencode":
        return model if "/" in model else f"{provider}/{model}"
    if harness == "kiro":
        return kiro_model_format(model)
    return model


def kiro_model_format(model: str) -> str:
    """Convert canonical dash-version model IDs to kiro's dot-version format.

    Kiro uses dots for minor versions (e.g. claude-sonnet-4.5) while the
    canonical catalog uses dashes (claude-sonnet-4-5). This handles any
    Claude family name (sonnet, opus, haiku, fable, mythos, etc.).
    """
    m = _KIRO_MODEL_RE.match(model)
    if m:
        suffix = m.group(3) or ""
        return f"{m.group(1)}.{m.group(2)}{suffix}"
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
    # Normalize the candidate to the harness-expected format before checking support
    formatted = _format_for_harness(candidate, _provider_for(harness, candidate), harness)
    if not _supported(harness, formatted):
        warnings.append(f"Model '{candidate}' is not in the {harness} harness registry. Falling back to auto/default.")
        return None, warnings
    return formatted, warnings
