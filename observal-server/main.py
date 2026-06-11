# SPDX-FileCopyrightText: 2026 Aryan Iyappan <aryaniyappan2006@gmail.com>
# SPDX-FileCopyrightText: 2026 Subramania Raja <dhanpraja231@gmail.com>
# SPDX-FileCopyrightText: 2026 Harishankar <harishankar0301@gmail.com>
# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-FileCopyrightText: 2026 Kaushik Kumar <kaushikrjpm10@gmail.com>
# SPDX-FileCopyrightText: 2026 Lokesh Selvam <lokeshselvam7025@gmail.com>
# SPDX-FileCopyrightText: 2026 Naraen Rammoorthi <naraen13@gmail.com>
# SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
# SPDX-FileCopyrightText: 2026 Shreem Seth <shreemseth26@gmail.com>
# SPDX-FileCopyrightText: 2026 Swathi Saravanan <ss4522@cornell.edu>
# SPDX-FileCopyrightText: 2026 Vishnu Muthiah <vishnu.muthiah04@gmail.com>
# SPDX-FileCopyrightText: 2026 Yash Gadgil <yashgadgil08@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

import os
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from loguru import logger as optic
from prometheus_fastapi_instrumentator import Instrumentator
from redis.exceptions import RedisError
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.middleware.sessions import SessionMiddleware
from starlette.requests import Request
from strawberry.fastapi import GraphQLRouter

import services.dynamic_settings as ds
from api.deps import get_db, get_or_create_default_org
from api.graphql import get_context_dep, schema
from api.middleware.audit import AuditMiddleware
from api.middleware.content_type import ContentTypeMiddleware
from api.middleware.request_id import RequestIDMiddleware
from api.middleware.trusted_proxy import TrustedProxyMiddleware
from api.ratelimit import limiter
from api.routes.admin import router as admin_router
from api.routes.agent import router as agent_router
from api.routes.alert import router as alert_router
from api.routes.audit import router as audit_router
from api.routes.auth import router as auth_router
from api.routes.bulk import router as bulk_router
from api.routes.co_authors import router as co_authors_router
from api.routes.component_source import router as component_source_router
from api.routes.config import router as config_router
from api.routes.dashboard import router as dashboard_router
from api.routes.device_auth import router as device_auth_router
from api.routes.feedback import router as feedback_router
from api.routes.hook import router as hook_router
from api.routes.ingest import router as ingest_router
from api.routes.insights import router as insights_router
from api.routes.invite import router as invite_router
from api.routes.jwks import router as jwks_router
from api.routes.layer_snapshot import router as layer_snapshot_router
from api.routes.logs_stream import router as logs_stream_router
from api.routes.mcp import router as mcp_router
from api.routes.preview import router as preview_router
from api.routes.prompt import router as prompt_router
from api.routes.reconcile import router as reconcile_router
from api.routes.registry_models import router as registry_models_router
from api.routes.review import router as review_router
from api.routes.sandbox import router as sandbox_router
from api.routes.sessions import router as sessions_router
from api.routes.skill import router as skill_router
from api.routes.support import router as support_router
from api.routes.telemetry import router as telemetry_router
from config import HAS_LICENSE, check_legacy_env_vars, settings
from database import engine
from logging_config import setup_logging
from models import Base
from models.user import User
from services.audit import AUDIT_LICENSED, setup_audit, shutdown_audit
from services.cache import close_cache, init_cache
from services.clickhouse import init_clickhouse
from services.crypto import init_key_manager
from services.optic import setup_optic
from services.redis import close as close_redis

setup_logging()
setup_optic(mode="prod" if HAS_LICENSE else "dev")


async def _ensure_columns(conn):
    """Add columns that may be missing on existing databases."""
    from sqlalchemy import text

    stmts = [
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS password_hash VARCHAR(255)",
        "ALTER TABLE mcp_listings ADD COLUMN IF NOT EXISTS environment_variables JSONB",
        "ALTER TABLE agent_versions ADD COLUMN IF NOT EXISTS models_by_ide JSONB NOT NULL DEFAULT '{}'::jsonb",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS avatar_url TEXT",
    ]
    for stmt in stmts:
        try:
            await conn.execute(text(stmt))
        except Exception:
            pass  # column already exists or DB doesn't support IF NOT EXISTS

    try:
        await conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS is_demo BOOLEAN DEFAULT false"))
    except Exception:
        pass


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Refuse to start if legacy env vars are set
    check_legacy_env_vars()
    # Load dynamic settings cache before anything else

    await ds.load_sync_cache()

    # Re-encrypt sensitive values if SECRET_KEY was rotated
    await ds.reencrypt_on_key_rotation()

    # ── Unsafe-default guards (non-local deployments only) ─────────────────
    if HAS_LICENSE:
        weak_secrets = {"change-me-to-a-random-string", "changeme", "secret", "dev", ""}
        if settings.SECRET_KEY in weak_secrets or len(settings.SECRET_KEY) < 32:
            raise RuntimeError(
                "SECRET_KEY is insecure. Set a random string of at least 32 characters "
                "before running in non-local mode."
            )

    skip_ddl = settings.SKIP_DDL_ON_STARTUP
    if not skip_ddl:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            await _ensure_columns(conn)
        await init_clickhouse()
    await init_cache()
    # Initialize asymmetric key manager for JWT signing
    init_key_manager(
        key_dir=settings.JWT_KEY_DIR,
        key_password=settings.JWT_KEY_PASSWORD,
    )

    from database import async_session as _session_factory

    # Migrate refresh token expiry: 7 → 30 days
    async with _session_factory() as db:
        from models.enterprise_config import EnterpriseConfig

        result = await db.execute(
            select(EnterpriseConfig).where(EnterpriseConfig.key == "jwt.refresh_token_expire_days")
        )
        cfg = result.scalar_one_or_none()
        if cfg and cfg.value == "7":
            cfg.value = "30"
            await db.commit()
            await ds.invalidate("jwt.refresh_token_expire_days")
            await ds.refresh_sync_cache()

    # Ensure default org exists and backfill any users missing one
    async with _session_factory() as db:
        default_org = await get_or_create_default_org(db)
        await db.execute(update(User).where(User.org_id.is_(None)).values(org_id=default_org.id))
        await db.commit()

    # Seed demo accounts when no real users exist and DEMO_* env vars are set
    from services.demo_accounts import seed_demo_accounts

    async with _session_factory() as db:
        await seed_demo_accounts(db)

    # Product analytics (PostHog) bus subscribers. Registering is always safe:
    # every capture is a no-op unless PRODUCT_ANALYTICS_ENABLED + key are set.
    import services.product_analytics_handlers  # noqa: F401
    import services.gtm_signup_handlers  # noqa: F401

    # Initialize enterprise audit system (license-gated)
    if AUDIT_LICENSED:
        setup_audit()

    # Wire insights dependencies (no-op if package not installed)
    from services.insights import configure_insights

    configure_insights()

    # Start agent registry cache for registered-agents-only filtering
    from services.agent_registry_cache import start as start_registry_cache

    await start_registry_cache()

    yield

    if AUDIT_LICENSED:
        await shutdown_audit()

    # Flush any queued product analytics events (no-op when disabled)
    import services.product_analytics as product_analytics

    product_analytics.shutdown()

    from services.agent_registry_cache import stop as stop_registry_cache

    await stop_registry_cache()
    await close_cache()
    await close_redis()


# Create the FastAPI app
_expose_openapi = ds.get_sync_bool("observability.enable_openapi") or not HAS_LICENSE
app = FastAPI(
    title="Observal API",
    description="API for Observal Agents & Capabilities Hub",
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/docs" if _expose_openapi else None,
    redoc_url="/redoc" if _expose_openapi else None,
    openapi_url="/openapi.json" if _expose_openapi else None,
)

# Rate limiting
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


@app.middleware("http")
async def _set_rate_limit_defaults(request: Request, call_next):
    """Workaround for slowapi 0.1.9 bug: when swallow_errors swallows a Redis
    failure, request.state.view_rate_limit is never set, causing an
    AttributeError in the post-response header injection."""
    request.state.view_rate_limit = None
    return await call_next(request)


@app.middleware("http")
async def _version_middleware(request: Request, call_next):
    """Version negotiation middleware.

    Computes effective = min(cli_version, server_version) and sets response headers.
    Route handlers can access request.state.effective_version for feature gating.
    """
    from version import get_server_version

    server_ver = get_server_version()

    cli_ver_str = request.headers.get("x-observal-cli-version")
    effective = server_ver

    if cli_ver_str:
        try:
            from packaging.version import Version

            client_ver = Version(cli_ver_str)
            sv = Version(server_ver)
            effective = str(min(client_ver, sv))
        except Exception:
            pass

    request.state.effective_version = effective

    response = await call_next(request)

    response.headers["X-Observal-Server"] = server_ver
    response.headers["X-Observal-Effective"] = effective
    return response


async def _redis_error_handler(request: Request, exc: RedisError):
    optic.error("redis_error", method=request.method, path=request.url.path, error=str(exc))
    return JSONResponse(status_code=503, content={"detail": "Service temporarily unavailable"})


app.add_exception_handler(RedisError, _redis_error_handler)

# Add SessionMiddleware for Authlib (OAuth state)
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.SECRET_KEY,
    max_age=3600,  # 1 hour
)

# --- CORS configuration ---
_cors_env = os.environ.get("CORS_ALLOWED_ORIGINS", "http://localhost:3000")
CORS_ALLOWED_ORIGINS: list[str] = [o.strip() for o in _cors_env.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "X-Request-ID"],
)

# --- Request body size limit (pure ASGI) ---
MAX_REQUEST_SIZE_BYTES: int = int(os.environ.get("MAX_REQUEST_SIZE_MB", "10")) * 1024 * 1024


class RequestSizeLimitMiddleware:
    """Reject requests whose Content-Length exceeds the configured limit.

    Pure ASGI implementation — avoids BaseHTTPMiddleware overhead (no forced
    response buffering, no extra task per request).
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = dict(scope.get("headers", []))
        content_length = headers.get(b"content-length")
        if content_length and int(content_length) > MAX_REQUEST_SIZE_BYTES:
            response = JSONResponse(status_code=413, content={"detail": "Request body too large"})
            await response(scope, receive, send)
            return
        await self.app(scope, receive, send)


app.add_middleware(RequestSizeLimitMiddleware)


# --- Security headers (pure ASGI) ---
_is_localhost = any(o.startswith("http://localhost") or o.startswith("http://127.0.0.1") for o in CORS_ALLOWED_ORIGINS)

_SECURITY_HEADERS: list[tuple[bytes, bytes]] = [
    (b"x-content-type-options", b"nosniff"),
    (b"x-frame-options", b"DENY"),
    (b"x-xss-protection", b"1; mode=block"),
    (b"referrer-policy", b"strict-origin-when-cross-origin"),
    (b"permissions-policy", b"camera=(), microphone=(), geolocation=()"),
    (
        b"content-security-policy",
        (
            b"default-src 'self'; "
            b"script-src 'self'; "
            b"style-src 'self' 'unsafe-inline'; "
            b"img-src 'self' data: https:; "
            b"font-src 'self'; "
            b"connect-src 'self' https:; "
            b"frame-ancestors 'none'; "
            b"base-uri 'self'; "
            b"form-action 'self'"
        ),
    ),
    (b"x-permitted-cross-domain-policies", b"none"),
]
if not _is_localhost:
    _SECURITY_HEADERS.append((b"strict-transport-security", b"max-age=31536000; includeSubDomains"))


class SecurityHeadersMiddleware:
    """Attach common security headers to every HTTP response.

    Pure ASGI implementation — injects headers during the response start
    message without buffering the response body.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message):
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.extend(_SECURITY_HEADERS)
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_with_headers)


app.add_middleware(SecurityHeadersMiddleware)

# --- Content-Type validation & JSON depth protection ---
app.add_middleware(ContentTypeMiddleware)

# --- Request ID ---
app.add_middleware(RequestIDMiddleware)

# --- Audit logging (enterprise, license-gated) ---
if AUDIT_LICENSED:
    app.add_middleware(AuditMiddleware)

# --- GZip compression handled by nginx (docker/nginx.conf gzip on) ---
# Removed Python-level GZipMiddleware to avoid redundant CPU cost.
# nginx compresses application/json responses in compiled C, much faster
# than Python's zlib. Response still arrives compressed to clients.

# --- Trusted proxy: resolve real client IP + scheme (SEC-003) ---
# Replaces Uvicorn --proxy-headers so proxy trust is controlled by a single
# dynamic setting (security.trusted_proxy_ips) shared with the rate limiter.
app.add_middleware(TrustedProxyMiddleware)


class CacheControlMiddleware:
    """Set Cache-Control headers on responses served from cache.

    Pure ASGI implementation — inspects response headers during start
    without buffering.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_cache_control(message):
            if message["type"] == "http.response.start":
                headers = dict(message.get("headers", []))
                cache_header = headers.get(b"x-fastapi-cache", b"").decode()
                if cache_header == "HIT" or (scope["method"] == "GET" and cache_header == "MISS"):
                    extra = [
                        (b"cache-control", f"public, max-age={ds.get_sync_int('data.cache_ttl_default', 30)}".encode())
                    ]
                    msg_headers = list(message.get("headers", []))
                    msg_headers.extend(extra)
                    message = {**message, "headers": msg_headers}
            await send(message)

        await self.app(scope, receive, send_with_cache_control)


app.add_middleware(CacheControlMiddleware)

# Enterprise routes + middleware (must be registered before startup)
if HAS_LICENSE:
    try:
        from ee import register_enterprise_middleware
        from ee.observal_server.routes import mount_ee_routes

        register_enterprise_middleware(app, settings)
        mount_ee_routes(app)
    except (ImportError, RuntimeError) as _ee_err:
        pass
        optic.warning("enterprise features unavailable: {}", str(_ee_err))
        app.state.enterprise_issues = [str(_ee_err)]

# GraphQL (replaces REST dashboard endpoints)
graphql_app = GraphQLRouter(schema, context_getter=get_context_dep)
app.include_router(graphql_app, prefix="/api/v1/graphql")

# REST (CLI operations, auth, telemetry ingestion)
app.include_router(auth_router)
app.include_router(device_auth_router)
app.include_router(jwks_router)
app.include_router(mcp_router)
app.include_router(review_router)
app.include_router(agent_router)
app.include_router(preview_router)
app.include_router(skill_router)
app.include_router(hook_router)
app.include_router(prompt_router)
app.include_router(sandbox_router)
app.include_router(telemetry_router)
app.include_router(dashboard_router)
app.include_router(feedback_router)
app.include_router(insights_router)
app.include_router(invite_router)
app.include_router(reconcile_router)
app.include_router(ingest_router)
app.include_router(admin_router)
app.include_router(alert_router)
app.include_router(sessions_router)
app.include_router(component_source_router)
app.include_router(bulk_router)
app.include_router(co_authors_router)
app.include_router(config_router)
app.include_router(registry_models_router)
app.include_router(support_router)
app.include_router(layer_snapshot_router)
app.include_router(logs_stream_router)
# Audit CLI event endpoint (license-gated internally, mounted always so
# CLI gets a clean 200 "skipped" response rather than 404 when unlicensed)
app.include_router(audit_router)

# --- Prometheus metrics ---
_instrumentator = Instrumentator(
    excluded_handlers=["/livez", "/healthz", "/readyz", "/metrics"],
).instrument(app)
if ds.get_sync_bool("observability.enable_metrics") or not HAS_LICENSE:
    _instrumentator.expose(app, endpoint="/metrics", include_in_schema=False)


@app.get("/livez", include_in_schema=False)
@app.get("/healthz", include_in_schema=False)
async def liveness():
    """K8s liveness probe. Returns 200 if the process is alive. No I/O."""
    return {"status": "alive"}


@app.get("/readyz", include_in_schema=False)
@app.get("/health")
async def readiness(db: AsyncSession = Depends(get_db)):
    """K8s readiness probe. Checks Postgres, ClickHouse, and Redis connectivity."""
    checks: dict[str, object] = {"status": "ok"}

    # Postgres
    try:
        count = await db.scalar(select(func.count()).select_from(User))
        checks["postgres"] = "ok"
        checks["initialized"] = (count or 0) > 0
    except Exception:
        checks["postgres"] = "unreachable"
        checks["status"] = "unhealthy"
        return JSONResponse(content=checks, status_code=503)

    # ClickHouse
    from services.clickhouse import clickhouse_health

    if not await clickhouse_health():
        checks["clickhouse"] = "unreachable"
        checks["status"] = "degraded"
    else:
        checks["clickhouse"] = "ok"

    # Redis
    from services.redis import ping as redis_ping

    if not await redis_ping():
        checks["redis"] = "unreachable"
        checks["status"] = "degraded"
    else:
        checks["redis"] = "ok"

    if HAS_LICENSE:
        issues = getattr(app.state, "enterprise_issues", [])
        if issues:
            checks["status"] = "degraded"

    return checks
