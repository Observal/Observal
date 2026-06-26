# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy import select, update

import services.dynamic_settings as ds
from api.deps import get_or_create_default_org
from config import HAS_LICENSE, check_legacy_env_vars, settings
from database import engine
from models import Base
from models.user import User
from services.audit import AUDIT_LICENSED, setup_audit, shutdown_audit
from services.cache import close_cache, init_cache
from services.clickhouse import init_clickhouse
from services.crypto import init_key_manager
from services.redis import close as close_redis


async def ensure_columns(conn) -> None:
    """Add columns that may be missing on existing databases."""
    from sqlalchemy import text

    stmts = [
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS password_hash VARCHAR(255)",
        "ALTER TABLE mcp_listings ADD COLUMN IF NOT EXISTS environment_variables JSONB",
        "ALTER TABLE agent_versions ADD COLUMN IF NOT EXISTS models_by_harness JSONB NOT NULL DEFAULT '{}'::jsonb",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS avatar_url TEXT",
    ]
    for stmt in stmts:
        try:
            await conn.execute(text(stmt))
        except Exception:
            pass

    try:
        await conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS is_demo BOOLEAN DEFAULT false"))
    except Exception:
        pass


async def run_startup_tasks() -> None:
    """Initialize application dependencies used by the FastAPI lifespan."""
    check_legacy_env_vars()

    if not settings.SKIP_DDL_ON_STARTUP:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            await ensure_columns(conn)
        await init_clickhouse()

    await ds.load_sync_cache()
    await ds.import_sso_env_once()
    await ds.reencrypt_on_key_rotation()

    from api.routes.auth import configure_oauth_client

    configure_oauth_client()

    if HAS_LICENSE:
        weak_secrets = {"change-me-to-a-random-string", "changeme", "secret", "dev", ""}
        if settings.SECRET_KEY in weak_secrets or len(settings.SECRET_KEY) < 32:
            raise RuntimeError(
                "SECRET_KEY is insecure. Set a random string of at least 32 characters "
                "before running in non-local mode."
            )

    await init_cache()
    init_key_manager(
        key_dir=settings.JWT_KEY_DIR,
        key_password=settings.JWT_KEY_PASSWORD,
    )

    from database import async_session as session_factory

    async with session_factory() as db:
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

    async with session_factory() as db:
        default_org = await get_or_create_default_org(db)
        await db.execute(update(User).where(User.org_id.is_(None)).values(org_id=default_org.id))
        await db.commit()

    from services.demo_accounts import seed_demo_accounts

    async with session_factory() as db:
        await seed_demo_accounts(db)

    if AUDIT_LICENSED:
        setup_audit()

    from services.insights import configure_insights

    configure_insights()

    from services.agent_registry_cache import start as start_registry_cache

    await start_registry_cache()


async def run_shutdown_tasks() -> None:
    """Release application dependencies used by the FastAPI lifespan."""
    if AUDIT_LICENSED:
        await shutdown_audit()

    from services.agent_registry_cache import stop as stop_registry_cache

    await stop_registry_cache()
    await close_cache()
    await close_redis()


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    await run_startup_tasks()
    yield
    await run_shutdown_tasks()
