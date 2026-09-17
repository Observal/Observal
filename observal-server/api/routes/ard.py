# SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""Agentic Resource Discovery endpoints.

Spec surface (v0.91, vendored under ``vendor/ard``):

    GET  /.well-known/ard.json          manifest
    GET  /.well-known/ai-catalog.json   predecessor path, same document
    POST /api/v1/ard/search             Search (mandatory)
    GET  /api/v1/ard/agents             List (optional, deterministic browse)
    POST /api/v1/ard/explore            Explore (optional): answers 501 until facets ship

Observal-specific:

    GET  /api/v1/ard/entries/{identifier}   one complete entry by identifier

Authentication is optional everywhere here. Anonymous callers see public,
approved entries only when ``discovery.public_search`` is on; authenticated
callers see what the registry's visibility rules already grant them.
"""

import re
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from loguru import logger as optic
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

import services.dynamic_settings as ds
from api.deps import get_db, optional_current_user
from api.ratelimit import limiter
from models.discovery_entry import DiscoveryEntry, DiscoveryLifecycle
from models.user import User
from schemas.ard import ArdExploreRequest, ArdSearchRequest
from services.discovery.identity import normalize_media_type, normalize_urn
from services.discovery.projection import ProjectionContext
from services.discovery.search import (
    DEFAULT_PAGE_SIZE,
    MAX_PAGE_SIZE,
    InvalidSearchRequestError,
    SearchFilters,
    decode_page_token,
    encode_page_token,
    search_entries,
)
from services.discovery.serialize import entry_document, list_item, manifest, search_result_item
from services.discovery.visibility import visible_entries_predicate

router = APIRouter(tags=["ard"])

PUBLIC_SEARCH_SETTING = "discovery.public_search"
MANIFEST_LIMIT = 5000
SEARCH_RATE_LIMIT = "60/minute"


# ── Helpers ──────────────────────────────────────────────────────────────


def _error(status: int, code: str, message: str) -> JSONResponse:
    """ARD Appendix B error envelope."""
    return JSONResponse(status_code=status, content={"errorCode": code, "message": message})


async def _context() -> ProjectionContext:
    return ProjectionContext.from_public_url(await ds.get("deployment.public_url", ""))


async def _public_search_enabled() -> bool:
    return await ds.get_bool(PUBLIC_SEARCH_SETTING, False)


def _search_source(ctx: ProjectionContext) -> str:
    return f"{ctx.artifact_base_url}/api/v1/ard"


# ── Well-known manifest ──────────────────────────────────────────────────


async def _manifest_response(db: AsyncSession) -> JSONResponse:
    ctx = await _context()
    entries: list[DiscoveryEntry] = []
    if await _public_search_enabled():
        stmt = (
            select(DiscoveryEntry)
            .where(visible_entries_predicate(None, lifecycles=(DiscoveryLifecycle.approved,)))
            .order_by(DiscoveryEntry.display_name, DiscoveryEntry.ard_identifier)
            .limit(MANIFEST_LIMIT)
        )
        entries = list((await db.execute(stmt)).scalars().all())
    optic.debug("ard manifest served entries={}", len(entries))
    return JSONResponse(
        content=manifest(entries, publisher_domain=ctx.publisher_domain, base_url=ctx.artifact_base_url),
        headers={"Cache-Control": "public, max-age=300"},
    )


@router.get("/.well-known/ard.json", include_in_schema=False)
async def well_known_ard(db: AsyncSession = Depends(get_db)) -> JSONResponse:
    return await _manifest_response(db)


@router.get("/.well-known/ai-catalog.json", include_in_schema=False)
async def well_known_ai_catalog(db: AsyncSession = Depends(get_db)) -> JSONResponse:
    """Predecessor path. Same document; consumers MAY consult it (spec §5.1)."""
    return await _manifest_response(db)


# ── Search ───────────────────────────────────────────────────────────────


@router.post("/api/v1/ard/search")
@limiter.limit(SEARCH_RATE_LIMIT)
async def ard_search(
    request: Request,
    body: ArdSearchRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(optional_current_user),
) -> JSONResponse:
    """ARD Search (§5.3.2). ``score`` is relevance only; approval and trust are separate fields."""
    ctx = await _context()
    try:
        filters = SearchFilters.from_ard_filter(body.query.filter)
        page = await search_entries(
            db,
            text=body.query.text or "",
            filters=filters,
            user=current_user,
            page_size=body.page_size or DEFAULT_PAGE_SIZE,
            page_token=body.page_token,
            public_search_enabled=await _public_search_enabled(),
        )
    except InvalidSearchRequestError as exc:
        return _error(400, "INVALID_ARGUMENT", str(exc))

    harness = filters.harnesses[0] if len(filters.harnesses) == 1 else None
    source = _search_source(ctx)
    content: dict[str, Any] = {"results": [search_result_item(r, source=source, harness=harness) for r in page.results]}
    if page.next_page_token:
        content["pageToken"] = page.next_page_token
    # Federation: an omitted field means "auto" bounded by the upstream allowlist
    # (ADR 0001, Decision 5). No upstreams are configured yet, so every mode is
    # local-only and there are no referrals to return.
    optic.debug(
        "ard search user={} results={} total={} federation={}",
        current_user.id if current_user else None,
        len(page.results),
        page.total,
        body.federation or "auto",
    )
    return JSONResponse(content=content, headers={"Cache-Control": "no-store"})


# ── Explore ──────────────────────────────────────────────────────────────


@router.post("/api/v1/ard/explore")
async def ard_explore(_body: ArdExploreRequest) -> JSONResponse:
    """ARD Explore is optional; a registry without it returns 501 (§5.3.3)."""
    return _error(501, "NOT_IMPLEMENTED", "Explore is not implemented by this registry yet.")


# ── List ─────────────────────────────────────────────────────────────────

_CLAUSE_RE = re.compile(r"^\s*(?P<field>[A-Za-z][A-Za-z0-9_.:-]*)\s*(?P<op>>=|<=|=|>|<)\s*(?P<value>.+?)\s*$")
_LIST_ORDER_FIELDS = {
    "displayname": DiscoveryEntry.display_name,
    "name": DiscoveryEntry.display_name,
    "updatedat": DiscoveryEntry.updated_at_source,
    "updated_at": DiscoveryEntry.updated_at_source,
    "createdat": DiscoveryEntry.indexed_at,
    "created_at": DiscoveryEntry.indexed_at,
    "version": DiscoveryEntry.version,
}


def _unquote(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
        return value[1:-1]
    return value


def _parse_timestamp(value: str) -> datetime:
    try:
        return datetime.fromisoformat(_unquote(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise InvalidSearchRequestError(f"invalid timestamp: {value}") from exc


def _apply_list_filter(stmt, expression: str | None):
    """Apply the List API's EBNF-like filter (Appendix A). Clauses are ANDed; values may be comma-ORed."""
    if not expression or not expression.strip():
        return stmt
    for clause in re.split(r"\s+AND\s+", expression.strip(), flags=re.IGNORECASE):
        match = _CLAUSE_RE.match(clause)
        if not match:
            raise InvalidSearchRequestError(f"invalid filter clause: {clause!r}")
        field = match.group("field").lower()
        op = match.group("op")
        raw_values = [_unquote(v) for v in match.group("value").split(",") if v.strip()]
        if field == "type":
            stmt = stmt.where(DiscoveryEntry.media_type.in_([normalize_media_type(v) or v for v in raw_values]))
        elif field in ("publisherid", "publisher"):
            stmt = stmt.where(DiscoveryEntry.publisher_domain.in_([v.lower() for v in raw_values]))
        elif field == "displayname":
            stmt = stmt.where(func.lower(DiscoveryEntry.display_name).like(f"%{raw_values[0].lower()}%"))
        elif field in ("obs:kind", "kind"):
            stmt = stmt.where(DiscoveryEntry.kind.in_(raw_values))
        elif field == "createdafter":
            stmt = stmt.where(DiscoveryEntry.indexed_at > _parse_timestamp(raw_values[0]))
        elif field == "updatedafter":
            stmt = stmt.where(DiscoveryEntry.updated_at_source > _parse_timestamp(raw_values[0]))
        else:
            raise InvalidSearchRequestError(f"unsupported filter field: {match.group('field')}")
        if op not in ("=", ">", ">=") or (op != "=" and field not in ("createdafter", "updatedafter")):
            raise InvalidSearchRequestError(f"operator {op!r} is not valid for {match.group('field')}")
    return stmt


def _apply_order(stmt, order_by: str | None):
    if not order_by or not order_by.strip():
        return stmt.order_by(DiscoveryEntry.display_name, DiscoveryEntry.ard_identifier)
    parts = order_by.strip().split()
    column = _LIST_ORDER_FIELDS.get(parts[0].lower())
    if column is None or len(parts) > 2 or (len(parts) == 2 and parts[1].upper() not in ("ASC", "DESC")):
        raise InvalidSearchRequestError(f"invalid orderBy: {order_by!r}")
    direction = column.desc() if len(parts) == 2 and parts[1].upper() == "DESC" else column.asc()
    return stmt.order_by(direction, DiscoveryEntry.ard_identifier)


@router.get("/api/v1/ard/agents")
async def ard_list(
    filter: str | None = Query(default=None, max_length=1000),  # spec parameter name
    order_by: str | None = Query(default=None, alias="orderBy", max_length=100),
    page_size: int = Query(default=20, alias="pageSize", ge=1, le=MAX_PAGE_SIZE),
    page_token: str | None = Query(default=None, alias="pageToken", max_length=512),
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(optional_current_user),
) -> JSONResponse:
    """ARD List (§5.3.4): deterministic, cacheable browsing with no relevance ranking."""
    if current_user is None and not await _public_search_enabled():
        return JSONResponse(content={"items": [], "total": 0}, headers={"Cache-Control": "no-store"})

    fingerprint = f"list:{filter or ''}|{order_by or ''}|{current_user.id if current_user else 'anon'}"
    try:
        offset = decode_page_token(page_token, fingerprint)
        base = select(DiscoveryEntry).where(visible_entries_predicate(current_user))
        base = _apply_list_filter(base, filter)
        stmt = _apply_order(base, order_by).offset(offset).limit(page_size + 1)
    except InvalidSearchRequestError as exc:
        return _error(400, "INVALID_ARGUMENT", str(exc))

    rows = list((await db.execute(stmt)).scalars().all())
    total = (await db.execute(select(func.count()).select_from(base.subquery()))).scalar_one()
    has_more = len(rows) > page_size
    items = [list_item(e) for e in rows[:page_size]]
    content: dict[str, Any] = {"items": items, "total": int(total)}
    if has_more:
        content["pageToken"] = encode_page_token(offset + page_size, fingerprint)
    return JSONResponse(content=content, headers={"Cache-Control": "no-store"})


# ── Entry by identifier ──────────────────────────────────────────────────


@router.get("/api/v1/ard/entries/{identifier:path}")
async def ard_entry(
    identifier: str,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(optional_current_user),
) -> JSONResponse:
    """Return one complete ARD entry. Observal-specific: the spec defines no fetch-by-id."""
    if current_user is None and not await _public_search_enabled():
        return _error(404, "NOT_FOUND", "Entry not found")
    urn = normalize_urn(identifier)
    lifecycles = tuple(DiscoveryLifecycle)  # archived is fine when asked for directly
    stmt = select(DiscoveryEntry).where(
        DiscoveryEntry.ard_identifier == urn, visible_entries_predicate(current_user, lifecycles=lifecycles)
    )
    entry = (await db.execute(stmt)).scalar_one_or_none()
    if entry is None:
        return _error(404, "NOT_FOUND", "Entry not found")
    return JSONResponse(content=entry_document(entry), headers={"Cache-Control": "no-store"})


__all__ = ["router"]
