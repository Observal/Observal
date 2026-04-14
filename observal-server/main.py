import logging
import os
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.sessions import SessionMiddleware
from starlette.requests import Request
from strawberry.fastapi import GraphQLRouter

from api.deps import get_db
from api.graphql import get_context_dep, schema
from api.middleware.content_type import ContentTypeMiddleware
from api.middleware.request_id import RequestIDMiddleware
from api.ratelimit import limiter
from api.routes.admin import router as admin_router
from api.routes.agent import router as agent_router
from api.routes.alert import router as alert_router
from api.routes.auth import router as auth_router
from api.routes.component_source import router as component_source_router
from api.routes.config import router as config_router
from api.routes.dashboard import router as dashboard_router
from api.routes.eval import router as eval_router
from api.routes.feedback import router as feedback_router
from api.routes.hook import router as hook_router
from api.routes.jwks import router as jwks_router
from api.routes.mcp import router as mcp_router
from api.routes.otel_dashboard import router as otel_dashboard_router
from api.routes.otlp import router as otlp_router
from api.routes.prompt import router as prompt_router
from api.routes.review import router as review_router
from api.routes.sandbox import router as sandbox_router
from api.routes.scan import router as scan_router
from api.routes.skill import router as skill_router
from api.routes.telemetry import router as telemetry_router
from config import settings
from database import engine
from models import Base
from models.user import User
from services.clickhouse import init_clickhouse
from services.crypto import init_key_manager
from services.redis import close as close_redis


async def _ensure_columns(conn):
    """Add columns that may be missing on existing databases."""
    from sqlalchemy import text

    stmts = [
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS password_hash VARCHAR(255)",
        "ALTER TABLE mcp_listings ADD COLUMN IF NOT EXISTS environment_variables JSONB",
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
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await _ensure_columns(conn)
    await init_clickhouse()
    # Initialize asymmetric key manager for JWT signing
    init_key_manager(
        key_dir=settings.JWT_KEY_DIR,
        key_password=settings.JWT_KEY_PASSWORD,
    )

    # Seed demo accounts when no real users exist and DEMO_* env vars are set
    from database import async_session as _session_factory
    from services.demo_accounts import seed_demo_accounts

    async with _session_factory() as db:
        await seed_demo_accounts(db)

    # Load enterprise module when in enterprise mode
    _logger = logging.getLogger("observal")
    if settings.DEPLOYMENT_MODE == "enterprise":
        try:
            from ee import register_enterprise

            register_enterprise(app, settings)
        except ImportError:
            _logger.error("DEPLOYMENT_MODE=enterprise but ee/ module not found")
            app.state.enterprise_issues = ["ee/ module not installed"]

    yield
    await close_redis()


# Create the FastAPI app
app = FastAPI(
    title="Observal API",
    description="API for Observal Agents & Capabilities Hub",
    version="0.1.0",
    lifespan=lifespan,
)

# Rate limiting
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

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
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Request body size limit ---
MAX_REQUEST_SIZE_BYTES: int = int(os.environ.get("MAX_REQUEST_SIZE_MB", "10")) * 1024 * 1024


class RequestSizeLimitMiddleware(BaseHTTPMiddleware):
    """Reject requests whose Content-Length exceeds the configured limit."""

    async def dispatch(self, request: Request, call_next):
        content_length = request.headers.get("content-length")
        if content_length and int(content_length) > MAX_REQUEST_SIZE_BYTES:
            return JSONResponse(
                status_code=413,
                content={"detail": "Request body too large"},
            )
        return await call_next(request)


app.add_middleware(RequestSizeLimitMiddleware)


# --- Security headers ---
_is_localhost = any(o.startswith("http://localhost") or o.startswith("http://127.0.0.1") for o in CORS_ALLOWED_ORIGINS)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Attach common security headers to every response."""

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        if not _is_localhost:
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return response


app.add_middleware(SecurityHeadersMiddleware)

# --- Content-Type validation & JSON depth protection ---
app.add_middleware(ContentTypeMiddleware)

# --- Request ID ---
app.add_middleware(RequestIDMiddleware)

# GraphQL (replaces REST dashboard endpoints)
graphql_app = GraphQLRouter(schema, context_getter=get_context_dep)
app.include_router(graphql_app, prefix="/api/v1/graphql")

# OTLP receiver (unauthenticated, standard paths — must be before /api/v1 routes)
app.include_router(otlp_router)

# REST (CLI operations, auth, telemetry ingestion)
app.include_router(auth_router)
app.include_router(jwks_router)
app.include_router(mcp_router)
app.include_router(review_router)
app.include_router(agent_router)
app.include_router(skill_router)
app.include_router(hook_router)
app.include_router(prompt_router)
app.include_router(sandbox_router)
app.include_router(scan_router)
app.include_router(telemetry_router)
app.include_router(dashboard_router)
app.include_router(feedback_router)
app.include_router(eval_router)
app.include_router(admin_router)
app.include_router(alert_router)
app.include_router(otel_dashboard_router)
app.include_router(component_source_router)
app.include_router(config_router)


@app.get("/healthz", include_in_schema=False)
async def liveness():
    """K8s liveness probe. Returns 200 if the process is alive. No I/O."""
    return {"status": "alive"}


@app.get("/health")
async def readiness(db: AsyncSession = Depends(get_db)):
    """K8s readiness probe. Checks DB connectivity, ClickHouse, and enterprise config."""
    checks: dict[str, object] = {"status": "ok"}

    try:
        count = await db.scalar(select(func.count()).select_from(User))
        checks["initialized"] = (count or 0) > 0
    except Exception:
        checks["status"] = "unhealthy"
        return JSONResponse(content=checks, status_code=503)

    # ClickHouse health
    from services.clickhouse import clickhouse_health

    if not await clickhouse_health():
        checks["clickhouse"] = "unreachable"
        checks["status"] = "degraded"
    else:
        checks["clickhouse"] = "ok"

    if settings.DEPLOYMENT_MODE == "enterprise":
        issues = getattr(app.state, "enterprise_issues", [])
        if issues:
            checks["status"] = "degraded"

    return checks
