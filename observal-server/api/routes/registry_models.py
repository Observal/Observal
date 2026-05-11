# SPDX-FileCopyrightText: 2026 Aryan Iyappan <aryaniyappan2006@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Public model catalog endpoints + admin refresh.

The catalog itself lives in ``services.model_catalog``. This route layer adds:

* HTTP caching headers (Cache-Control, ETag, If-None-Match) so the frontend
  TanStack Query hook + nginx + browser cache can short-circuit requests.
* Admin-only force refresh (rate-limited) that returns a diff for the
  diagnostics widget.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Header, Request, Response, status

from api.deps import get_current_user, require_role
from api.ratelimit import limiter
from models.user import User, UserRole
from schemas.models import Catalog
from services.model_catalog import diff_against_current, get_catalog

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["models"])


@router.get("/models", response_model=Catalog)
@limiter.limit("60/minute")
async def list_models(
    request: Request,
    response: Response,
    if_none_match: str | None = Header(default=None, alias="If-None-Match"),
    current_user: User = Depends(get_current_user),
):
    """Return the normalized model catalog.

    Conditional GET: when the client sends ``If-None-Match: <etag>`` and the
    catalog hasn't changed, we respond ``304 Not Modified`` with the same
    ``ETag`` so the client keeps its cached copy.
    """
    catalog = await get_catalog()

    response.headers["Cache-Control"] = "public, max-age=300, stale-while-revalidate=3600"
    if catalog.etag:
        response.headers["ETag"] = catalog.etag
    response.headers["X-Catalog-Source"] = catalog.source
    response.headers["X-Catalog-Degraded"] = "1" if catalog.degraded else "0"

    if catalog.etag and if_none_match and if_none_match.strip() == catalog.etag:
        return Response(
            status_code=status.HTTP_304_NOT_MODIFIED,
            headers={
                "ETag": catalog.etag,
                "Cache-Control": "public, max-age=300, stale-while-revalidate=3600",
                "X-Catalog-Source": catalog.source,
                "X-Catalog-Degraded": "1" if catalog.degraded else "0",
            },
        )

    return catalog


@router.post("/admin/models/refresh")
@limiter.limit("4/minute")
async def refresh_models(
    request: Request,
    current_user: User = Depends(require_role(UserRole.admin)),
):
    """Force a fresh fetch of models.dev and report what changed.

    Heavy, rate-limited (4/min/IP) so it can't be used to hammer the upstream.
    """
    prev = await get_catalog()
    diff = await diff_against_current(prev)
    new = await get_catalog()
    return {
        "ok": True,
        "diff": diff,
        "fetched_at": new.fetched_at.isoformat(),
        "source": new.source,
        "degraded": new.degraded,
        "model_count": new.model_count,
        "etag": new.etag,
        "upstream_etag": new.upstream_etag,
    }
