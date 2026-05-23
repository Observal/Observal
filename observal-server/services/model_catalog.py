# SPDX-FileCopyrightText: 2026 Aryan Iyappan <aryaniyappan2006@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Live model catalog service.

A small read-through cache around ``https://models.dev/api.json``. All callers
(public list endpoint, install fallback resolver, agent builder) go through
``get_catalog()``; nothing else in the project should fetch the upstream URL
directly.

Caching layers (defense in depth):

1. ``ETag`` / ``If-None-Match`` against the upstream so we never re-parse 1MB
   of unchanged JSON. Both the value and the upstream etag live in Redis.
2. Per-process LRU around the parsed ``Catalog`` keyed on the Redis cache
   version, expires after 60 s.
3. Redis cache (``observal:model_catalog:v1``) with 12h hard TTL plus
   stale-while-revalidate at 12h. Background pre-warm cron (every 6h) and
   single-flight refresh lock prevent stampedes.
4. HTTP response caching on the public route is layered above this service
   in ``api/routes/registry_models.py`` (Cache-Control + ETag).

Out-of-scope here: HTTP response caching, frontend caching, CLI file caching.
Those happen at the layer that uses the catalog.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from datetime import UTC, date, datetime
from pathlib import Path

import httpx
import structlog
from loguru import logger as optic

from schemas.models import Catalog, CatalogModel, ModelDisplay
from services.model_display import format_display
from services.redis import get_redis

logger = structlog.get_logger(__name__)

# ─── Constants ────────────────────────────────────────────────

UPSTREAM_URL = "https://models.dev/api.json"
CACHE_VERSION = "v1"
REDIS_VALUE_KEY = f"observal:model_catalog:{CACHE_VERSION}"
REDIS_ETAG_KEY = f"observal:model_catalog:{CACHE_VERSION}:etag"
REDIS_LOCK_KEY = f"observal:model_catalog:{CACHE_VERSION}:lock"
REDIS_TTL_SECONDS = 12 * 3600  # 12h hard TTL
SWR_AGE_SECONDS = 12 * 3600  # serve stale & refresh after 12h
LOCK_TTL_SECONDS = 30  # single-flight upper bound
INMEM_TTL_SECONDS = 60
REQUEST_TIMEOUT_SECONDS = 5.0
REQUEST_RETRIES = 1

SNAPSHOT_PATH = Path(__file__).resolve().parent.parent / "data" / "model_registry_seed.json"

# ─── Provider → IDE mapping (curated; in code, not data) ─────

PROVIDER_IDE_MAP: dict[str, list[str]] = {
    "anthropic": ["claude-code", "kiro", "opencode"],
    "openai": ["codex", "opencode"],
    "google": ["gemini-cli", "opencode"],
    "google-vertex": ["gemini-cli", "opencode"],
}


# ─── Per-IDE format dispatcher (in code, not data) ────────────


def format_for_ide(model_id: str, provider: str, ide: str) -> str:
    """Translate a canonical model_id to the string the IDE expects.

    - Claude Code accepts short family aliases (``opus``/``sonnet``/``haiku``)
      _or_ a full id; we prefer the alias when recognizable so existing user
      muscle memory is preserved.
    - OpenCode addresses models as ``provider/model_id``.
    - Kiro, Codex, Gemini CLI: take the raw id verbatim.
    """
    optic.debug("format_for_ide: model_id={}, provider={}, ide={}", model_id, provider, ide)
    if ide == "claude-code":
        lid = model_id.lower()
        for kw in ("opus", "sonnet", "haiku"):
            if kw in lid:
                return kw
        return model_id
    if ide == "opencode":
        return f"{provider}/{model_id}"
    return model_id


# ─── In-process LRU on the parsed catalog ────────────────────

_inmem_cache: dict[str, object] = {"catalog": None, "etag": None, "expires_at": 0.0}
_inmem_lock = asyncio.Lock()

# Hold strong refs to background refresh tasks so they aren't GCed mid-flight.
_BG_TASKS: set[asyncio.Task] = set()


def _spawn_background_refresh(etag: str | None) -> None:
    optic.debug("_spawn_background_refresh: etag={}", etag)
    task = asyncio.create_task(_background_refresh(etag))
    _BG_TASKS.add(task)
    task.add_done_callback(_BG_TASKS.discard)


def _inmem_get(current_etag: str | None) -> Catalog | None:
    """Return the in-memory parsed Catalog if still fresh and matching ``current_etag``."""
    optic.debug("_inmem_get: current_etag={}", current_etag)
    if not current_etag:
        return None
    cat = _inmem_cache.get("catalog")
    etag = _inmem_cache.get("etag")
    expires = float(_inmem_cache.get("expires_at") or 0.0)
    if cat and etag == current_etag and time.monotonic() < expires:
        return cat  # type: ignore[return-value]
    return None


def _inmem_set(cat: Catalog, etag: str | None) -> None:
    optic.debug("_inmem_set: cat={}, etag={}", cat, etag)
    _inmem_cache["catalog"] = cat
    _inmem_cache["etag"] = etag
    _inmem_cache["expires_at"] = time.monotonic() + INMEM_TTL_SECONDS


# ─── Normalization ───────────────────────────────────────────


def _parse_date(value) -> date | None:
    optic.debug("_parse_date: value={}", value)
    if not value:
        return None
    if isinstance(value, date):
        return value
    try:
        return datetime.fromisoformat(str(value)).date()
    except ValueError:
        try:
            return datetime.strptime(str(value), "%Y-%m-%d").date()
        except ValueError:
            return None


def _normalize_models_dev(payload: dict) -> list[CatalogModel]:
    """Walk the models.dev shape and emit ``CatalogModel`` rows for the providers we map to IDEs."""
    optic.debug("_normalize_models_dev: payload={}", payload)
    rows: list[CatalogModel] = []
    for provider_id, provider in payload.items():
        if provider_id not in PROVIDER_IDE_MAP:
            continue
        models = provider.get("models", {}) if isinstance(provider, dict) else {}
        for model_id, model in models.items():
            if not isinstance(model, dict):
                continue
            cost = model.get("cost") or {}
            limit = model.get("limit") or {}
            capabilities: list[str] = []
            for flag in ("tool_call", "reasoning", "attachment"):
                if model.get(flag):
                    capabilities.append(flag)
            modalities = model.get("modalities") or {}
            inputs = modalities.get("input") or []
            if "image" in inputs and "vision" not in capabilities:
                capabilities.append("vision")

            rows.append(
                CatalogModel(
                    model_id=model.get("id") or model_id,
                    display_name=model.get("name") or model_id,
                    provider=provider_id,
                    family=model.get("family") or "",
                    release_date=_parse_date(model.get("release_date")),
                    last_updated=_parse_date(model.get("last_updated")),
                    context_window=limit.get("context") if isinstance(limit, dict) else None,
                    output_tokens=limit.get("output") if isinstance(limit, dict) else None,
                    cost_input=cost.get("input") if isinstance(cost, dict) else None,
                    cost_output=cost.get("output") if isinstance(cost, dict) else None,
                    capabilities=capabilities,
                    supported_ides=PROVIDER_IDE_MAP.get(provider_id, []),
                    deprecated=bool(model.get("deprecated")),
                )
            )
    return rows


def _attach_display_fields(models: list[CatalogModel]) -> None:
    """Mutate ``models`` to carry pre-computed display fields (parity with frontend)."""
    optic.debug("_attach_display_fields: models={}", models)
    primary_counts: dict[str, int] = {}
    primaries: list[str] = []
    for m in models:
        primary, _, _ = format_display(m.display_name, m.model_id, m.release_date)
        primaries.append(primary)
        primary_counts[primary] = primary_counts.get(primary, 0) + 1

    for m, primary in zip(models, primaries, strict=True):
        primary_text, secondary, is_rolling = format_display(
            m.display_name,
            m.model_id,
            m.release_date,
            disambiguate=primary_counts[primary] > 1,
        )
        m.display = ModelDisplay(
            primary=primary_text,
            secondary=secondary,
            is_rolling=is_rolling,
            is_deprecated=m.deprecated,
        )


def _hash_etag(payload: dict) -> str:
    """Compute a stable etag from the payload (used when the upstream omits ETag)."""
    optic.debug("_hash_etag: payload={}", payload)
    h = hashlib.sha256()
    h.update(json.dumps(payload, sort_keys=True).encode())
    return f'W/"{h.hexdigest()[:16]}"'


# ─── Snapshot fallback ────────────────────────────────────────


def _load_snapshot_payload() -> dict | None:
    optic.debug("_load_snapshot_payload called")
    if not SNAPSHOT_PATH.exists():
        return None
    try:
        with SNAPSHOT_PATH.open("r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        logger.warning("model_catalog_snapshot_load_failed", error=str(e), path=str(SNAPSHOT_PATH))
        return None


# ─── Redis layer ─────────────────────────────────────────────


def _serialize_catalog(cat: Catalog) -> str:
    optic.debug("_serialize_catalog: cat={}", cat)
    return cat.model_dump_json()


def _deserialize_catalog(raw: str) -> Catalog:
    optic.debug("_deserialize_catalog: raw={}", raw)
    return Catalog.model_validate_json(raw)


async def _redis_load() -> tuple[Catalog | None, str | None, float | None]:
    """Return (catalog, upstream_etag, age_seconds_or_None)."""
    optic.debug("_redis_load called")
    try:
        r = get_redis()
        raw, upstream_etag = await r.mget(REDIS_VALUE_KEY, REDIS_ETAG_KEY)
    except Exception as e:
        logger.debug("model_catalog_redis_load_failed", error=str(e))
        return None, None, None
    if not raw:
        return None, upstream_etag, None
    try:
        cat = _deserialize_catalog(raw)
    except Exception as e:
        logger.warning("model_catalog_redis_deserialize_failed", error=str(e))
        return None, upstream_etag, None
    age = (datetime.now(UTC) - cat.fetched_at).total_seconds() if cat.fetched_at else None
    return cat, upstream_etag, age


async def _redis_store(cat: Catalog, upstream_etag: str | None) -> None:
    optic.debug("_redis_store: cat={}, upstream_etag={}", cat, upstream_etag)
    try:
        r = get_redis()
        async with r.pipeline(transaction=False) as pipe:
            pipe.set(REDIS_VALUE_KEY, _serialize_catalog(cat), ex=REDIS_TTL_SECONDS)
            if upstream_etag:
                pipe.set(REDIS_ETAG_KEY, upstream_etag, ex=REDIS_TTL_SECONDS)
            else:
                pipe.delete(REDIS_ETAG_KEY)
            await pipe.execute()
    except Exception as e:
        logger.warning("model_catalog_redis_store_failed", error=str(e))


# ─── Single-flight refresh ───────────────────────────────────


async def _acquire_refresh_lock() -> bool:
    """Try to grab the cross-process refresh lock. ``True`` means "we own the refresh"."""
    optic.debug("_acquire_refresh_lock called")
    try:
        r = get_redis()
        return bool(await r.set(REDIS_LOCK_KEY, "1", nx=True, ex=LOCK_TTL_SECONDS))
    except Exception:
        return True  # Best effort: if Redis is down, just refresh anyway.


async def _release_refresh_lock() -> None:
    optic.debug("_release_refresh_lock called")
    try:
        r = get_redis()
        await r.delete(REDIS_LOCK_KEY)
    except Exception:
        pass


# ─── Upstream fetch ──────────────────────────────────────────


async def _fetch_upstream(prev_etag: str | None) -> tuple[dict | None, str | None, bool]:
    """GET ``models.dev/api.json``.

    Returns ``(payload_or_None, etag_or_None, not_modified)``. ``payload_or_None``
    is None when the request returned 304 or when the request failed.
    """
    optic.debug("_fetch_upstream: prev_etag={}", prev_etag)
    headers = {"Accept": "application/json", "User-Agent": "observal/1.0"}
    if prev_etag:
        headers["If-None-Match"] = prev_etag

    last_exc: Exception | None = None
    for attempt in range(REQUEST_RETRIES + 1):
        try:
            async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS) as client:
                resp = await client.get(UPSTREAM_URL, headers=headers)
            if resp.status_code == 304:
                return None, prev_etag, True
            if resp.status_code != 200:
                logger.warning("model_catalog_upstream_status", status=resp.status_code)
                continue
            payload = resp.json()
            etag = resp.headers.get("ETag") or resp.headers.get("etag") or _hash_etag(payload)
            return payload, etag, False
        except (httpx.HTTPError, httpx.TimeoutException, json.JSONDecodeError) as e:  # type: ignore[attr-defined]
            last_exc = e
            if attempt < REQUEST_RETRIES:
                await asyncio.sleep(0.25 * (attempt + 1))
                continue
            break
    if last_exc is not None:
        logger.warning("model_catalog_upstream_failed", error=str(last_exc))
    return None, prev_etag, False


# ─── Public entrypoint ───────────────────────────────────────


async def get_catalog(force_refresh: bool = False) -> Catalog:
    """Return the normalized model catalog.

    1. Cheap path: in-memory LRU keyed on Redis upstream etag (60s).
    2. Try Redis. Serve fresh entries directly. If stale, return them and
       schedule a background refresh.
    3. On Redis miss: fetch upstream (with ``If-None-Match``), normalize,
       write to Redis.
    4. On all upstream failures: fall back to the vendored snapshot.
    5. On every failure: return an empty Catalog with ``degraded=True``.
    """
    optic.debug("get_catalog: force_refresh={}", force_refresh)
    # Step 1: Try Redis first to know the current etag.
    cat, upstream_etag, age = await _redis_load()

    if not force_refresh:
        # In-memory hot path
        cached = _inmem_get(upstream_etag)
        if cached is not None:
            cached.source = "redis"
            return cached
        # Redis hit and fresh
        if cat is not None and age is not None and age < SWR_AGE_SECONDS:
            cat.source = "redis"
            _inmem_set(cat, upstream_etag)
            return cat
        # Redis hit but stale: serve stale, kick a background refresh
        if cat is not None and age is not None and age >= SWR_AGE_SECONDS:
            cat.source = "redis"
            _inmem_set(cat, upstream_etag)
            _spawn_background_refresh(upstream_etag)
            return cat

    # Step 2: Redis miss (or forced refresh). Try upstream.
    return await _refresh(prev_etag=upstream_etag)


async def _background_refresh(prev_etag: str | None) -> None:
    """Fire-and-forget refresh used by stale-while-revalidate."""
    optic.debug("_background_refresh: prev_etag={}", prev_etag)
    if not await _acquire_refresh_lock():
        return  # Another worker beat us to it.
    try:
        await _refresh(prev_etag=prev_etag)
    except Exception as e:
        logger.warning("model_catalog_background_refresh_failed", error=str(e))
    finally:
        await _release_refresh_lock()


async def _refresh(prev_etag: str | None) -> Catalog:
    """Always-online refresh path: fetch + normalize + persist."""
    optic.debug("_refresh: prev_etag={}", prev_etag)
    async with _inmem_lock:
        # Re-check after acquiring the lock; another coroutine may have refreshed.
        cached_cat, cached_etag, cached_age = await _redis_load()
        if (
            cached_cat is not None
            and cached_age is not None
            and cached_age < SWR_AGE_SECONDS
            and not _force_refresh_requested()
        ):
            cached_cat.source = "redis"
            _inmem_set(cached_cat, cached_etag)
            return cached_cat

        payload, etag, not_modified = await _fetch_upstream(prev_etag)

        if not_modified and cached_cat is not None:
            # Upstream confirmed unchanged. Refresh fetched_at & TTL only.
            cached_cat.fetched_at = datetime.now(UTC)
            cached_cat.source = "live"
            cached_cat.etag = cached_etag or etag
            cached_cat.upstream_etag = etag or cached_etag
            await _redis_store(cached_cat, etag or cached_etag)
            _inmem_set(cached_cat, etag or cached_etag)
            return cached_cat

        if payload is not None:
            cat = _build_catalog(payload, source="live", upstream_etag=etag)
            await _redis_store(cat, etag)
            _inmem_set(cat, etag)
            return cat

        # Upstream unreachable. Fall back to vendored snapshot.
        snapshot = _load_snapshot_payload()
        if snapshot is not None:
            cat = _build_catalog(snapshot, source="snapshot", upstream_etag=None, degraded=True)
            # Don't poison Redis with the snapshot; just hold it in-process.
            _inmem_set(cat, None)
            return cat

        # Last-resort empty catalog so the API surfaces ``degraded=True``.
        return Catalog(
            models=[],
            fetched_at=datetime.now(UTC),
            source="empty",
            degraded=True,
            etag=None,
            upstream_etag=None,
            model_count=0,
        )


def _force_refresh_requested() -> bool:
    """Stub hook that other layers (admin refresh route) can extend in the future."""
    optic.debug("_force_refresh_requested called")
    return False


def _build_catalog(payload: dict, *, source: str, upstream_etag: str | None, degraded: bool = False) -> Catalog:
    optic.debug("_build_catalog: payload={}, source={}, upstream_etag={}", payload, source, upstream_etag)
    models = _normalize_models_dev(payload)
    _attach_display_fields(models)
    fetched_at = datetime.now(UTC)
    self_etag = _self_etag(fetched_at, upstream_etag)
    return Catalog(
        models=models,
        fetched_at=fetched_at,
        source=source,  # type: ignore[arg-type]
        degraded=degraded,
        etag=self_etag,
        upstream_etag=upstream_etag,
        model_count=len(models),
    )


def _self_etag(fetched_at: datetime, upstream_etag: str | None) -> str:
    """Compute an etag for HTTP responses derived from fetched_at + upstream etag."""
    optic.debug("_self_etag: fetched_at={}, upstream_etag={}", fetched_at, upstream_etag)
    h = hashlib.sha256()
    h.update(fetched_at.isoformat().encode())
    h.update((upstream_etag or "").encode())
    return f'W/"{h.hexdigest()[:16]}"'


# ─── Diff helper for the admin refresh response ──────────────


async def diff_against_current(prev: Catalog | None) -> dict:
    """Compute add/remove/update sets between the previous in-Redis catalog and the now-current one.

    Used by ``POST /api/v1/admin/models/refresh`` so ops gets a one-shot sense
    of what changed when they pull a new release of models.dev.
    """
    optic.debug("diff_against_current: prev={}", prev)
    new = await get_catalog(force_refresh=True)
    if prev is None:
        return {"added": [m.model_id for m in new.models], "removed": [], "updated": [], "total": new.model_count}
    prev_ids = {m.model_id: m for m in prev.models}
    new_ids = {m.model_id: m for m in new.models}
    added = sorted(set(new_ids) - set(prev_ids))
    removed = sorted(set(prev_ids) - set(new_ids))
    updated: list[str] = []
    for mid in set(prev_ids) & set(new_ids):
        if prev_ids[mid].model_dump(exclude={"display"}) != new_ids[mid].model_dump(exclude={"display"}):
            updated.append(mid)
    return {"added": added, "removed": removed, "updated": sorted(updated), "total": new.model_count}
