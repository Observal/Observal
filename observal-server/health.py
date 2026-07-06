# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: Apache-2.0

from collections.abc import Callable

from fastapi import APIRouter, Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from prometheus_fastapi_instrumentator import Instrumentator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

import services.dynamic_settings as ds
from api.deps import get_db
from config import HAS_LICENSE
from models.user import User

router = APIRouter()
LicenseGetter = Callable[[], bool]


def get_license_enabled(request: Request) -> bool:
    license_getter = getattr(request.app.state, "has_license", None)
    if license_getter is not None:
        return bool(license_getter())
    return HAS_LICENSE


@router.get("/livez", include_in_schema=False)
@router.get("/healthz", include_in_schema=False)
async def liveness():
    """K8s liveness probe. Returns 200 if the process is alive. No I/O."""
    return {"status": "alive"}


@router.get("/readyz", include_in_schema=False)
@router.get("/health")
async def readiness(request: Request, db: AsyncSession = Depends(get_db)):
    """K8s readiness probe. Checks Postgres, ClickHouse, and Redis connectivity."""
    checks: dict[str, object] = {"status": "ok"}

    try:
        count = await db.scalar(select(func.count()).select_from(User))
        checks["postgres"] = "ok"
        checks["initialized"] = (count or 0) > 0
    except Exception:
        checks["postgres"] = "unreachable"
        checks["status"] = "unhealthy"
        return JSONResponse(content=checks, status_code=503)

    from services.clickhouse import clickhouse_health

    if not await clickhouse_health():
        checks["clickhouse"] = "unreachable"
        checks["status"] = "degraded"
    else:
        checks["clickhouse"] = "ok"

    from services.redis import ping as redis_ping

    if not await redis_ping():
        checks["redis"] = "unreachable"
        checks["status"] = "degraded"
    else:
        checks["redis"] = "ok"

    if get_license_enabled(request):
        issues = getattr(request.app.state, "enterprise_issues", [])
        if issues:
            checks["status"] = "degraded"

    return checks


def configure_health_and_metrics(app: FastAPI, has_license_getter: LicenseGetter | None = None) -> None:
    license_getter = has_license_getter or (lambda: HAS_LICENSE)
    app.state.has_license = license_getter
    instrumentator = Instrumentator(
        excluded_handlers=["/livez", "/healthz", "/readyz", "/metrics"],
    ).instrument(app)
    if ds.get_sync_bool("observability.enable_metrics") or not license_getter():
        instrumentator.expose(app, endpoint="/metrics", include_in_schema=False)
    app.include_router(router)
