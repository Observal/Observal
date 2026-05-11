# SPDX-FileCopyrightText: 2026 Aryan Iyappan <aryaniyappan2006@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Single source of truth for "what model should this IDE config use?".

Two entry points:

- ``resolve_model_for_ide(ide, agent_version, override=None)``
    Async. Validates the candidate against the live catalog and falls back
    to the IDE's auto sentinel with a warning when the model is unknown or
    the IDE doesn't support it. When the catalog is degraded (no upstream
    and no snapshot) we trust the saved value verbatim and emit a soft
    warning rather than overwriting the user's choice.
- ``resolve_saved_value(ide, model_name, models_by_ide)``
    Sync. Pure lookup that returns the IDE-formatted string the user asked
    for, or ``None`` (meaning "emit auto sentinel"). Used by the offline
    manifest builder, which doesn't have a Redis context.

Both go through ``services.model_catalog.format_for_ide`` so the per-IDE
format rules (Claude Code aliases, OpenCode provider prefix, …) live in one
place.
"""

from __future__ import annotations

import structlog

from schemas.ide_registry import accepts_model_choice
from services.model_catalog import (
    PROVIDER_IDE_MAP,
    Catalog,
    format_for_ide,
    get_catalog,
)

logger = structlog.get_logger(__name__)


def _candidate_for_ide(ide: str, models_by_ide: dict | None, model_name: str | None) -> str | None:
    """Pick the saved model the user wants for ``ide``.

    Precedence:
        1. Per-IDE override from ``models_by_ide``.
        2. ``model_name`` — but only for Claude Code (legacy default).
    Other IDEs default to None (= emit auto sentinel) when no override exists.
    """
    if models_by_ide and ide in models_by_ide and models_by_ide[ide]:
        return models_by_ide[ide]
    if ide == "claude-code" and model_name:
        return model_name
    return None


def _format(ide: str, candidate: str | None, catalog: Catalog | None) -> str | None:
    if not candidate:
        return None
    provider = "anthropic"  # safe default for the legacy claude-code path
    if catalog is not None:
        for entry in catalog.models:
            if entry.model_id == candidate:
                provider = entry.provider
                break
    return format_for_ide(candidate, provider, ide)


def resolve_saved_value(ide: str, model_name: str, models_by_ide: dict | None) -> str | None:
    """Sync resolver — no catalog lookup. Used by the offline manifest builder.

    Returns the IDE-formatted string for the saved value, or ``None`` if no
    saved value exists (caller must emit the auto sentinel).
    """
    if not accepts_model_choice(ide):
        return None
    candidate = _candidate_for_ide(ide, models_by_ide, model_name)
    return _format(ide, candidate, None) if candidate else None


async def resolve_model_for_ide(
    ide: str,
    *,
    model_name: str = "",
    models_by_ide: dict | None = None,
    override: str | None = None,
) -> tuple[str | None, list[str]]:
    """Resolve the effective model for an online install.

    Returns ``(emitted_value_or_None, warnings)``. ``None`` means the caller
    should emit the IDE's auto sentinel (e.g. drop the ``model:`` line for
    Claude Code, write ``"model": null`` for Kiro).
    """
    warnings: list[str] = []

    if not accepts_model_choice(ide):
        if override:
            warnings.append(f"{ide} does not accept a model choice; ignoring --model {override}.")
        return None, warnings

    candidate = override or _candidate_for_ide(ide, models_by_ide, model_name)
    if not candidate:
        return None, warnings

    # Claude Code short aliases ("sonnet", "opus", "haiku") and the literal
    # "inherit" sentinel are passed through verbatim — they don't appear in the
    # catalog and the IDE itself accepts them.
    if ide == "claude-code" and candidate.lower() in ("sonnet", "opus", "haiku", "inherit"):
        if candidate.lower() == "inherit":
            return None, warnings
        return candidate.lower(), warnings

    try:
        catalog = await get_catalog()
    except Exception as e:
        logger.warning("model_resolver_catalog_error", error=str(e))
        catalog = None

    if catalog is None or catalog.degraded:
        warnings.append(
            "Model catalog is unavailable; using the saved selection verbatim. "
            "Re-run after the catalog refreshes if the IDE rejects the model."
        )
        return _format(ide, candidate, catalog), warnings

    # Look up the candidate in the catalog
    matches = [m for m in catalog.models if m.model_id == candidate]
    if not matches:
        warnings.append(f"Model '{candidate}' is not in the catalog. Falling back to {ide}'s auto/default.")
        return None, warnings

    entry = matches[0]
    if ide not in entry.supported_ides:
        provider_ides = PROVIDER_IDE_MAP.get(entry.provider, [])
        warnings.append(
            f"Model '{candidate}' (provider {entry.provider}) is not supported by {ide}. "
            f"Provider routes to: {', '.join(provider_ides) or 'no IDE'}. Falling back to auto."
        )
        return None, warnings

    if entry.deprecated:
        warnings.append(f"Model '{candidate}' is marked deprecated by the upstream catalog.")

    return format_for_ide(entry.model_id, entry.provider, ide), warnings
