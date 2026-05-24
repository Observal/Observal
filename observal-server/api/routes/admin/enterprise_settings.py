# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Admin settings, diagnostics, and resource tuning routes."""

import json

from fastapi import Depends, HTTPException
from loguru import logger as optic
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

import services.dynamic_settings as ds
from api.deps import get_db, require_role
from config import HAS_LICENSE, settings
from models.enterprise_config import EnterpriseConfig
from models.user import User, UserRole
from schemas.admin import EnterpriseConfigResponse, EnterpriseConfigUpdate
from services.audit_helpers import audit
from services.security_events import EventType, SecurityEvent, Severity, emit_security_event

from ._router import router
from .helpers import _validate_branding_app_name, _validate_branding_logo

# ── Diagnostics ─────────────────────────────────────────


@router.get("/diagnostics")
async def diagnostics(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin)),
):
    """Authenticated system health - full status for ops dashboards."""
    optic.debug("diagnostics called")
    from services.crypto import get_key_manager

    diag: dict[str, object] = {
        "status": "ok",
        "licensed": HAS_LICENSE,
        "checks": {},
    }

    # Database
    try:
        await db.execute(text("SELECT 1"))
        user_count = await db.scalar(select(func.count()).select_from(User))
        demo_count = await db.scalar(select(func.count()).select_from(User).where(User.is_demo.is_(True)))
        diag["checks"]["database"] = {
            "status": "ok",
            "users": user_count or 0,
            "demo_accounts": demo_count or 0,
        }
    except Exception as e:
        diag["checks"]["database"] = {"status": "error", "detail": str(e)}
        diag["status"] = "unhealthy"

    # JWT keys
    try:
        get_key_manager()
        diag["checks"]["jwt_keys"] = {
            "status": "ok",
            "algorithm": settings.JWT_SIGNING_ALGORITHM,
        }
    except RuntimeError:
        diag["checks"]["jwt_keys"] = {
            "status": "missing",
            "algorithm": settings.JWT_SIGNING_ALGORITHM,
        }

    # Enterprise config
    if HAS_LICENSE:
        issues: list[str] = []
        if settings.SECRET_KEY == "change-me-to-a-random-string":
            issues.append("SECRET_KEY is using default value")
        sso_only = await ds.get_bool("deployment.sso_only")
        frontend_url = await ds.get("deployment.frontend_url")
        if sso_only and not settings.OAUTH_CLIENT_ID:
            issues.append("OAUTH_CLIENT_ID is not set (required for SSO-only mode)")
        if frontend_url in ("http://localhost:3000", ""):
            issues.append("deployment.frontend_url is localhost")
        diag["checks"]["enterprise"] = {
            "status": "ok" if not issues else "misconfigured",
            "sso_only": sso_only,
            "sso_configured": bool(settings.OAUTH_CLIENT_ID),
            "issues": issues,
        }
        if issues:
            diag["status"] = "degraded"

    await audit(current_user, "admin.diagnostics.view", "diagnostics")
    return diag


@router.get("/system-warnings", response_model=list[dict])
async def system_warnings(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin)),
):
    """Return actionable security warnings for the admin settings page."""
    optic.debug("system_warnings called")
    warnings: list[dict] = []

    weak_keys = {"change-me-to-a-random-string", "changeme", "secret", "dev", ""}
    if settings.SECRET_KEY in weak_keys or len(settings.SECRET_KEY) < 32:
        warnings.append(
            {
                "level": "critical",
                "code": "weak_secret_key",
                "message": "SECRET_KEY is insecure. Set a random string of at least 32 characters.",
            }
        )

    demo_count = await db.scalar(select(func.count()).select_from(User).where(User.is_demo.is_(True)))
    if demo_count:
        warnings.append(
            {
                "level": "warning",
                "code": "demo_accounts_active",
                "message": f"{demo_count} demo account(s) are still active. Remove them or change their passwords before going to production.",
            }
        )

    return warnings


@router.get("/settings", response_model=list[EnterpriseConfigResponse])
async def list_settings(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin)),
):
    optic.debug("admin settings list")
    result = await db.execute(select(EnterpriseConfig).order_by(EnterpriseConfig.key))
    configs = [EnterpriseConfigResponse.model_validate(c) for c in result.scalars().all()]
    await audit(current_user, "admin.settings.list", "settings")
    return configs


@router.get("/settings/{key}", response_model=EnterpriseConfigResponse)
async def get_setting(
    key: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin)),
):
    optic.debug("admin setting get")
    result = await db.execute(select(EnterpriseConfig).where(EnterpriseConfig.key == key))
    cfg = result.scalar_one_or_none()
    if not cfg:
        raise HTTPException(status_code=404, detail="Setting not found")
    await audit(current_user, "admin.settings.view", "settings", resource_name=key)
    return EnterpriseConfigResponse.model_validate(cfg)


@router.put("/settings/{key}", response_model=EnterpriseConfigResponse)
async def upsert_setting(
    key: str,
    req: EnterpriseConfigUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin)),
):
    optic.debug("upsert_setting: key={}", key)
    if key in ("branding.logo", "branding.wordmark"):
        _validate_branding_logo(req.value)
    elif key == "branding.app_name":
        _validate_branding_app_name(req.value)

    result = await db.execute(select(EnterpriseConfig).where(EnterpriseConfig.key == key))
    cfg = result.scalar_one_or_none()
    if cfg:
        cfg.value = req.value
    else:
        cfg = EnterpriseConfig(key=key, value=req.value)
        db.add(cfg)
    await db.commit()
    await db.refresh(cfg)
    await emit_security_event(
        SecurityEvent(
            event_type=EventType.SETTING_CHANGED,
            severity=Severity.WARNING,
            outcome="success",
            actor_id=str(current_user.id),
            actor_email=current_user.email,
            actor_role=current_user.role.value,
            target_id=key,
            target_type="setting",
        )
    )
    await audit(current_user, "admin.settings.update", "settings", resource_name=key)
    return EnterpriseConfigResponse.model_validate(cfg)


@router.delete("/settings/{key}")
async def delete_setting(
    key: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin)),
):
    optic.debug("delete_setting: key={}", key)
    result = await db.execute(select(EnterpriseConfig).where(EnterpriseConfig.key == key))
    cfg = result.scalar_one_or_none()
    if not cfg:
        raise HTTPException(status_code=404, detail="Setting not found")
    await db.delete(cfg)
    await db.commit()
    await audit(current_user, "admin.settings.delete", "settings", resource_name=key)
    return {"deleted": key}


@router.post("/resources/apply")
async def apply_resources(
    current_user: User = Depends(require_role(UserRole.admin)),
    db: AsyncSession = Depends(get_db),
):
    """Re-apply resource tuning settings to ClickHouse without restart."""
    optic.debug("apply_resources: user_id={}", current_user.id)
    from services.clickhouse import RESOURCE_SETTINGS_MAP, apply_resource_settings

    result = await db.execute(select(EnterpriseConfig).where(EnterpriseConfig.key.like("resource.%")))
    current = {cfg.key: cfg.value for cfg in result.scalars().all()}

    await apply_resource_settings(overrides=current)

    await emit_security_event(
        SecurityEvent(
            event_type=EventType.SETTING_CHANGED,
            severity=Severity.WARNING,
            outcome="success",
            actor_id=str(current_user.id),
            actor_email=current_user.email,
            actor_role=current_user.role.value,
            target_id="resource_settings",
            target_type="setting",
            detail=f"Applied resource settings: {list(current.keys())}",
        )
    )

    applied_keys = [k for k in current if k in RESOURCE_SETTINGS_MAP]
    await audit(
        current_user,
        "admin.resources.apply",
        "resources",
        detail=json.dumps(applied_keys),
    )
    return {
        "applied": {k: current[k] for k in applied_keys},
        "message": "ClickHouse resource settings applied",
    }
