"""CLI-side model catalog access with a 1h read-through file cache.

The CLI fetches the catalog from ``GET /api/v1/models`` and caches the JSON
to ``~/.observal/cache/model_catalog.json``. The cache is consulted before
hitting the server so the interactive ``observal pull`` model picker stays
snappy even on a flaky network.

Cache invalidation:
* TTL: 1 hour (matches the in-memory horizon on the server-side LRU).
* ``observal pull --refresh-models`` and ``observal registry models list --refresh``
  both bypass the cache and force a re-fetch.
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any

from observal_cli import client

logger = logging.getLogger(__name__)

_DEFAULT_TTL_SECONDS = 3600  # 1 hour
_CACHE_FILE = Path(os.environ.get("OBSERVAL_HOME", str(Path.home() / ".observal"))) / "cache" / "model_catalog.json"
_OFFLINE_MIRROR = Path(__file__).resolve().parent.parent / "observal-server" / "data" / "model_registry_seed.json"


# ─── File cache I/O ──────────────────────────────────────────


def _read_file_cache() -> dict | None:
    """Return the cached catalog if it exists and is parseable. None otherwise."""
    try:
        if not _CACHE_FILE.exists():
            return None
        with _CACHE_FILE.open("r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        logger.debug("model_catalog_cli_cache_read_failed", exc_info=e)
        return None


def _write_file_cache(payload: dict) -> None:
    try:
        _CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        with _CACHE_FILE.open("w", encoding="utf-8") as f:
            json.dump(payload, f)
    except OSError as e:
        logger.debug("model_catalog_cli_cache_write_failed", exc_info=e)


def invalidate_cache() -> None:
    """Delete the cached catalog. Used by the ``--refresh-models`` flag."""
    try:
        if _CACHE_FILE.exists():
            _CACHE_FILE.unlink()
    except OSError as e:
        logger.debug("model_catalog_cli_cache_invalidate_failed", exc_info=e)


# ─── Public entrypoint ───────────────────────────────────────


def fetch_catalog(*, refresh: bool = False, ttl: int = _DEFAULT_TTL_SECONDS) -> dict:
    """Return the catalog as a plain dict.

    Order of preference:
    1. Fresh file cache (when ``refresh`` is False and the cached_at age < ``ttl``).
    2. ``GET /api/v1/models`` from the configured server.
    3. Stale file cache (any age) — better than nothing.
    4. Vendored offline mirror snapshot (``observal-server/data/model_registry_seed.json``).
    5. Empty catalog with ``degraded=True``.
    """
    if not refresh:
        cached = _read_file_cache()
        if cached:
            cached_at = float(cached.get("_cached_at") or 0.0)
            if cached_at and (time.time() - cached_at) < ttl:
                cached["_source"] = "file"
                return cached

    try:
        data = client.get("/api/v1/models")
    except Exception as e:
        logger.debug("model_catalog_cli_remote_fetch_failed", exc_info=e)
        data = None

    if data:
        data["_cached_at"] = time.time()
        data["_source"] = "live"
        _write_file_cache(data)
        return data

    stale = _read_file_cache()
    if stale:
        stale["_source"] = "file-stale"
        return stale

    if _OFFLINE_MIRROR.exists():
        try:
            with _OFFLINE_MIRROR.open("r", encoding="utf-8") as f:
                snapshot = json.load(f)
            return _normalize_offline_snapshot(snapshot)
        except (OSError, json.JSONDecodeError) as e:
            logger.debug("model_catalog_cli_offline_mirror_read_failed", exc_info=e)

    return {"models": [], "model_count": 0, "degraded": True, "source": "empty", "_source": "empty"}


# ─── Helpers used by callers ─────────────────────────────────


def models_supporting_ide(catalog: dict, ide: str) -> list[dict]:
    """Filter the catalog to models that this IDE accepts."""
    out: list[dict] = []
    for m in catalog.get("models") or []:
        ides = m.get("supported_ides") or []
        if ide in ides:
            out.append(m)
    return out


def model_choices_for_picker(catalog: dict, ide: str) -> list[tuple[str, str]]:
    """Return ``[(label, model_id), ...]`` suitable for ``select_one``.

    For Claude Code we surface the short-alias choices first (sonnet/opus/haiku/inherit)
    so muscle memory keeps working, then the catalog options.
    """
    from observal_cli.render import format_model

    choices: list[tuple[str, str]] = []
    if ide in ("claude-code", "claude_code"):
        choices.append(("inherit (use main session model)", "inherit"))
        for short in ("sonnet", "opus", "haiku"):
            choices.append((short, short))

    rows = models_supporting_ide(catalog, ide)
    for m in rows:
        primary, secondary, _ = format_model(m, disambiguate=True)
        label = f"{primary} ({secondary})" if secondary else primary
        choices.append((label, m.get("model_id") or ""))
    return choices


# Mirrors ``services.model_catalog.PROVIDER_IDE_MAP`` — kept locally so the CLI
# can fall back to the offline snapshot without importing from the server pkg.
_PROVIDER_IDE_MAP: dict[str, list[str]] = {
    "anthropic": ["claude-code", "kiro", "opencode"],
    "openai": ["codex", "opencode"],
    "google": ["gemini-cli", "opencode"],
    "google-vertex": ["gemini-cli", "opencode"],
}


def _normalize_offline_snapshot(snapshot: Any) -> dict:
    """Best-effort map of the raw models.dev snapshot to the {models, ...} shape.

    Used only when we can't reach the server. The picker doesn't need every
    field — just ``model_id``, ``display_name``, ``provider``, ``supported_ides``
    and a release date.
    """
    rows: list[dict] = []
    if isinstance(snapshot, dict):
        for provider_id, provider in snapshot.items():
            if provider_id not in _PROVIDER_IDE_MAP:
                continue
            models = provider.get("models", {}) if isinstance(provider, dict) else {}
            for model_id, m in models.items():
                if not isinstance(m, dict):
                    continue
                rows.append(
                    {
                        "model_id": m.get("id") or model_id,
                        "display_name": m.get("name") or model_id,
                        "provider": provider_id,
                        "release_date": str(m.get("release_date") or ""),
                        "supported_ides": _PROVIDER_IDE_MAP.get(provider_id, []),
                        "deprecated": bool(m.get("deprecated")),
                    }
                )
    return {
        "models": rows,
        "model_count": len(rows),
        "degraded": True,
        "source": "snapshot",
        "_source": "offline-mirror",
    }
