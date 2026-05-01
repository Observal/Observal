import hashlib
import json
import logging
import secrets
import uuid

from fastapi import APIRouter, Depends, HTTPException
from redis.exceptions import RedisError
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import ROLE_HIERARCHY, get_db, get_or_create_default_org, require_password_auth, require_role
from config import settings
from models.enterprise_config import EnterpriseConfig
from models.organization import Organization
from models.user import User, UserRole
from schemas.admin import (
    AdminResetPasswordRequest,
    EnterpriseConfigResponse,
    EnterpriseConfigUpdate,
    UserAdminResponse,
    UserCreateRequest,
    UserCreateResponse,
    UserRoleUpdate,
)
from services.audit_helpers import audit
from services.security_events import (
    EventType,
    SecurityEvent,
    Severity,
    emit_security_event,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])


# ── Diagnostics ─────────────────────────────────────────


@router.get("/diagnostics")
async def diagnostics(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin)),
):
    """Authenticated system health — full status for ops dashboards."""
    from services.crypto import get_key_manager

    diag: dict[str, object] = {
        "status": "ok",
        "deployment_mode": settings.DEPLOYMENT_MODE,
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
    if settings.DEPLOYMENT_MODE == "enterprise":
        issues: list[str] = []
        if settings.SECRET_KEY == "change-me-to-a-random-string":
            issues.append("SECRET_KEY is using default value")
        if settings.SSO_ONLY and not settings.OAUTH_CLIENT_ID:
            issues.append("OAUTH_CLIENT_ID is not set (required for SSO-only mode)")
        if settings.FRONTEND_URL in ("http://localhost:3000", ""):
            issues.append("FRONTEND_URL is localhost")
        diag["checks"]["enterprise"] = {
            "status": "ok" if not issues else "misconfigured",
            "sso_only": settings.SSO_ONLY,
            "sso_configured": bool(settings.OAUTH_CLIENT_ID),
            "issues": issues,
        }
        if issues:
            diag["status"] = "degraded"

    await audit(current_user, "admin.diagnostics.view", "diagnostics")
    return diag


# ── Enterprise Settings ──────────────────────────────────


@router.get("/settings", response_model=list[EnterpriseConfigResponse])
async def list_settings(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin)),
):
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
    result = await db.execute(select(EnterpriseConfig).where(EnterpriseConfig.key == key))
    cfg = result.scalar_one_or_none()
    if not cfg:
        raise HTTPException(status_code=404, detail="Setting not found")
    await db.delete(cfg)
    await db.commit()
    await audit(current_user, "admin.settings.delete", "settings", resource_name=key)
    return {"deleted": key}


# ── User Management ──────────────────────────────────────


@router.get("/users", response_model=list[UserAdminResponse])
async def list_users(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin)),
):
    stmt = select(User).order_by(User.created_at.desc())
    if current_user.org_id is not None:
        stmt = stmt.where(User.org_id == current_user.org_id)
    result = await db.execute(stmt)
    users = [UserAdminResponse.model_validate(u) for u in result.scalars().all()]
    await audit(current_user, "admin.users.list", "user")
    return users


@router.post("/users", response_model=UserCreateResponse, dependencies=[Depends(require_password_auth)])
async def create_user(
    req: UserCreateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin)),
):
    """Admin creates a new user and gets back their generated password."""
    existing = await db.execute(select(User).where(User.email == req.email))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Email already registered")

    try:
        role = UserRole(req.role)
    except ValueError:
        raise HTTPException(status_code=422, detail=f"Invalid role. Must be one of: {[r.value for r in UserRole]}")

    if ROLE_HIERARCHY.get(role, 999) < ROLE_HIERARCHY[current_user.role]:
        raise HTTPException(status_code=403, detail="Cannot assign a role higher than your own")

    password = req.password or await _generate_unique_password(db)

    org_id = current_user.org_id
    if not org_id:
        default_org = await get_or_create_default_org(db)
        org_id = default_org.id

    user = User(email=req.email, username=req.username, name=req.name, role=role, org_id=org_id)
    user.set_password(password)
    db.add(user)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="Email already registered")
    await db.refresh(user)

    await emit_security_event(
        SecurityEvent(
            event_type=EventType.USER_CREATED,
            severity=Severity.INFO,
            outcome="success",
            actor_id=str(current_user.id),
            actor_email=current_user.email,
            actor_role=current_user.role.value,
            target_id=str(user.id),
            target_type="user",
            detail=f"Created user {user.email} with role {role.value}",
        )
    )
    await audit(
        current_user,
        "admin.users.create",
        "user",
        resource_id=str(user.id),
        resource_name=user.email,
        detail=json.dumps({"role": role.value}),
    )
    return UserCreateResponse(
        id=user.id,
        email=user.email,
        username=user.username,
        name=user.name,
        role=user.role.value,
        password=password,
    )


@router.put("/users/{user_id}/role", response_model=UserAdminResponse)
async def update_user_role(
    user_id: uuid.UUID,
    req: UserRoleUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin)),
):
    try:
        new_role = UserRole(req.role)
    except ValueError:
        raise HTTPException(status_code=422, detail=f"Invalid role. Must be one of: {[r.value for r in UserRole]}")

    from api.deps import ROLE_HIERARCHY

    if ROLE_HIERARCHY.get(new_role, 999) < ROLE_HIERARCHY[current_user.role]:
        raise HTTPException(status_code=403, detail="Cannot assign a role higher than your own")

    if user_id == current_user.id and new_role != current_user.role:
        raise HTTPException(status_code=400, detail="Cannot change your own role")

    stmt = select(User).where(User.id == user_id)
    if current_user.org_id is not None:
        stmt = stmt.where(User.org_id == current_user.org_id)
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    old_role = user.role.value
    user.role = new_role
    await db.commit()
    await db.refresh(user)
    await emit_security_event(
        SecurityEvent(
            event_type=EventType.ROLE_CHANGED,
            severity=Severity.WARNING,
            outcome="success",
            actor_id=str(current_user.id),
            actor_email=current_user.email,
            actor_role=current_user.role.value,
            target_id=str(user.id),
            target_type="user",
            detail=f"Role changed from {old_role} to {new_role.value}",
        )
    )
    await audit(
        current_user,
        "admin.users.role_update",
        "user",
        resource_id=str(user.id),
        resource_name=user.email,
        detail=json.dumps({"old_role": old_role, "new_role": new_role.value}),
    )
    return UserAdminResponse.model_validate(user)


@router.put("/users/{user_id}/password", dependencies=[Depends(require_password_auth)])
async def reset_user_password(
    user_id: uuid.UUID,
    req: AdminResetPasswordRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin)),
):
    """Admin resets a user's password.

    Either provide new_password directly, or set generate=true to create
    a secure random password that doesn't collide with existing hashes.
    """
    stmt = select(User).where(User.id == user_id)
    if current_user.org_id is not None:
        stmt = stmt.where(User.org_id == current_user.org_id)
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if req.generate:
        new_password = await _generate_unique_password(db)
    elif req.new_password:
        new_password = req.new_password
    else:
        raise HTTPException(status_code=422, detail="Provide new_password or set generate=true")

    user.set_password(new_password)
    await db.commit()

    try:
        from services.redis import get_redis

        redis = get_redis()
        await redis.setex(f"must_change_password:{user.id}", 86400, "1")
    except (RedisError, Exception):
        pass

    await emit_security_event(
        SecurityEvent(
            event_type=EventType.ADMIN_PASSWORD_RESET,
            severity=Severity.WARNING,
            outcome="success",
            actor_id=str(current_user.id),
            actor_email=current_user.email,
            actor_role=current_user.role.value,
            target_id=str(user.id),
            target_type="user",
            detail=f"Password reset for {user.email}",
        )
    )
    logger.warning("Admin %s reset password for user %s", current_user.email, user.email)
    await audit(
        current_user,
        "admin.users.password_reset",
        "user",
        resource_id=str(user.id),
        resource_name=user.email,
    )

    resp: dict[str, str] = {"message": f"Password reset for {user.email}"}
    if req.generate:
        resp["generated_password"] = new_password
        resp["must_change_password"] = "true"
    return resp


async def _generate_unique_password(db: AsyncSession, length: int = 20, max_attempts: int = 10) -> str:
    """Generate a secure password whose hash doesn't collide with any existing password hash."""
    import os
    import string

    alphabet = string.ascii_letters + string.digits + string.punctuation
    result = await db.execute(select(User.password_hash).where(User.password_hash.is_not(None)))
    existing_hashes = {row[0] for row in result.all()}

    for _ in range(max_attempts):
        password = "".join(secrets.choice(alphabet) for _ in range(length))
        # Check against all existing password hashes
        salt = os.urandom(16)
        key = hashlib.scrypt(password.encode(), salt=salt, n=16384, r=8, p=1, dklen=32)
        candidate_hash = f"{salt.hex()}${key.hex()}"
        if candidate_hash not in existing_hashes:
            return password

    # Astronomically unlikely to reach here, but be safe
    return "".join(secrets.choice(alphabet) for _ in range(length))


@router.delete("/users/{user_id}", status_code=204)
async def delete_user(
    user_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin)),
):
    """Admin deletes a user account and all associated data."""
    if user_id == current_user.id:
        raise HTTPException(status_code=400, detail="Cannot delete yourself")

    stmt = select(User).where(User.id == user_id)
    if current_user.org_id is not None:
        stmt = stmt.where(User.org_id == current_user.org_id)
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Prevent deleting the last admin/super_admin
    if user.role in (UserRole.admin, UserRole.super_admin):
        admin_count = await db.scalar(
            select(func.count()).select_from(User).where(User.role.in_([UserRole.admin, UserRole.super_admin]))
        )
        if admin_count is not None and admin_count <= 1:
            raise HTTPException(status_code=400, detail="Cannot delete the last admin")

    logger.warning("Admin %s deleted user %s (%s)", current_user.email, user.email, user.id)
    deleted_user_email = user.email
    deleted_user_id = str(user.id)
    await emit_security_event(
        SecurityEvent(
            event_type=EventType.USER_DELETED,
            severity=Severity.WARNING,
            outcome="success",
            actor_id=str(current_user.id),
            actor_email=current_user.email,
            actor_role=current_user.role.value,
            target_id=deleted_user_id,
            target_type="user",
            detail=f"Deleted user {deleted_user_email}",
        )
    )
    await db.delete(user)
    await db.commit()
    await audit(
        current_user,
        "admin.users.delete",
        "user",
        resource_id=deleted_user_id,
        resource_name=deleted_user_email,
    )


# ── Penalty & Weight Customization ──────────────────────


@router.get("/penalties", response_model=list[dict])
async def list_penalties(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin)),
):
    """List all penalty definitions."""
    from models.scoring import PenaltyDefinition

    result = await db.execute(
        select(PenaltyDefinition).order_by(PenaltyDefinition.dimension, PenaltyDefinition.event_name)
    )
    penalties = [
        {
            "id": str(p.id),
            "dimension": p.dimension.value,
            "event_name": p.event_name,
            "amount": p.amount,
            "severity": p.severity.value,
            "trigger_type": p.trigger_type.value,
            "description": p.description,
            "is_active": p.is_active,
        }
        for p in result.scalars().all()
    ]
    await audit(current_user, "admin.penalties.list", "penalty")
    return penalties


@router.put("/penalties/{penalty_id}", response_model=dict)
async def update_penalty(
    penalty_id: uuid.UUID,
    req: dict,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin)),
):
    """Enable/disable or modify a penalty definition."""
    from models.scoring import PenaltyDefinition

    result = await db.execute(select(PenaltyDefinition).where(PenaltyDefinition.id == penalty_id))
    penalty = result.scalar_one_or_none()
    if not penalty:
        raise HTTPException(status_code=404, detail="Penalty not found")

    if "amount" in req:
        penalty.amount = int(req["amount"])
    if "is_active" in req:
        penalty.is_active = bool(req["is_active"])
    if "description" in req:
        penalty.description = str(req["description"])

    await db.commit()
    await db.refresh(penalty)
    await emit_security_event(
        SecurityEvent(
            event_type=EventType.PENALTY_WEIGHTS_MODIFIED,
            severity=Severity.INFO,
            outcome="success",
            actor_id=str(current_user.id),
            actor_email=current_user.email,
            actor_role=current_user.role.value,
            target_id=str(penalty_id),
            target_type="penalty",
            detail=f"Modified penalty {penalty.event_name}",
        )
    )
    await audit(
        current_user,
        "admin.penalties.update",
        "penalty",
        resource_id=str(penalty_id),
        resource_name=penalty.event_name,
    )
    return {
        "id": str(penalty.id),
        "event_name": penalty.event_name,
        "amount": penalty.amount,
        "is_active": penalty.is_active,
    }


@router.get("/weights", response_model=list[dict])
async def list_weights(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin)),
):
    """List global dimension weights."""
    from models.scoring import DEFAULT_DIMENSION_WEIGHTS, DimensionWeight

    result = await db.execute(select(DimensionWeight).where(DimensionWeight.agent_id.is_(None)))
    db_weights = {w.dimension.value: w.weight for w in result.scalars().all()}

    # Merge with defaults
    weights = []
    for dim, default_weight in DEFAULT_DIMENSION_WEIGHTS.items():
        weights.append(
            {
                "dimension": dim.value,
                "weight": db_weights.get(dim.value, default_weight),
                "is_custom": dim.value in db_weights,
            }
        )
    await audit(current_user, "admin.weights.list", "weights")
    return weights


@router.put("/weights", response_model=dict)
async def set_global_weights(
    req: dict,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin)),
):
    """Set global dimension weights. Body: {dimension: weight, ...}"""
    from models.scoring import DimensionWeight, ScoringDimension

    updated = {}
    for dim_name, weight in req.items():
        try:
            dim = ScoringDimension(dim_name)
        except ValueError:
            continue

        result = await db.execute(
            select(DimensionWeight).where(
                DimensionWeight.agent_id.is_(None),
                DimensionWeight.dimension == dim,
            )
        )
        existing = result.scalar_one_or_none()
        if existing:
            existing.weight = float(weight)
        else:
            db.add(DimensionWeight(dimension=dim, weight=float(weight)))
        updated[dim_name] = float(weight)

    await db.commit()
    await audit(
        current_user,
        "admin.weights.set_global",
        "weights",
        detail=json.dumps(updated),
    )
    return {"updated": updated}


@router.put("/weights/agents/{agent_id}", response_model=dict)
async def set_agent_weights(
    agent_id: uuid.UUID,
    req: dict,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin)),
):
    """Set per-agent dimension weights. Body: {dimension: weight, ...}"""
    from models.scoring import DimensionWeight, ScoringDimension

    updated = {}
    for dim_name, weight in req.items():
        try:
            dim = ScoringDimension(dim_name)
        except ValueError:
            continue

        result = await db.execute(
            select(DimensionWeight).where(
                DimensionWeight.agent_id == agent_id,
                DimensionWeight.dimension == dim,
            )
        )
        existing = result.scalar_one_or_none()
        if existing:
            existing.weight = float(weight)
        else:
            db.add(DimensionWeight(agent_id=agent_id, dimension=dim, weight=float(weight)))
        updated[dim_name] = float(weight)

    await db.commit()
    await audit(
        current_user,
        "admin.weights.set_agent",
        "weights",
        resource_id=str(agent_id),
        detail=json.dumps(updated),
    )
    return {"agent_id": str(agent_id), "updated": updated}


# ── Canary Configuration ──────────────────────────────────

# In-memory canary store (would be DB-backed in production)
_canary_configs: dict[str, list[dict]] = {}  # agent_id -> list of canary configs
_canary_reports: dict[str, list[dict]] = {}  # agent_id -> list of reports


@router.post("/canaries", response_model=dict)
async def create_canary(
    req: dict,
    current_user: User = Depends(require_role(UserRole.admin)),
):
    """Create a canary configuration for an agent."""
    from services.eval.canary import CanaryConfig

    agent_id = req.get("agent_id")
    if not agent_id:
        raise HTTPException(status_code=422, detail="agent_id required")

    config = CanaryConfig(
        agent_id=str(agent_id),
        enabled=True,
        canary_type=req.get("canary_type", "numeric"),
        injection_point=req.get("injection_point", "tool_output"),
        canary_value=req.get("canary_value", ""),
        expected_behavior=req.get("expected_behavior", "flag_anomaly"),
    )

    if agent_id not in _canary_configs:
        _canary_configs[agent_id] = []
    _canary_configs[agent_id].append(config.model_dump())

    await emit_security_event(
        SecurityEvent(
            event_type=EventType.CANARY_CREATED,
            severity=Severity.INFO,
            outcome="success",
            actor_id=str(current_user.id),
            actor_email=current_user.email,
            actor_role=current_user.role.value,
            target_id=str(agent_id),
            target_type="canary",
            detail=f"Canary type: {config.canary_type}",
        )
    )
    await audit(
        current_user,
        "admin.canaries.create",
        "canary",
        resource_id=config.id,
        detail=json.dumps({"agent_id": str(agent_id), "canary_type": config.canary_type}),
    )
    return {"id": config.id, "agent_id": agent_id, "canary_type": config.canary_type}


@router.get("/canaries/{agent_id}", response_model=list[dict])
async def list_canaries(
    agent_id: str,
    current_user: User = Depends(require_role(UserRole.admin)),
):
    """List canary configs for an agent."""
    configs = _canary_configs.get(agent_id, [])
    await audit(current_user, "admin.canaries.list", "canary", resource_id=agent_id)
    return configs


@router.get("/canaries/{agent_id}/reports", response_model=list[dict])
async def list_canary_reports(
    agent_id: str,
    current_user: User = Depends(require_role(UserRole.admin)),
):
    """List canary reports with pass/fail stats."""
    reports = _canary_reports.get(agent_id, [])
    await audit(current_user, "admin.canaries.reports", "canary", resource_id=agent_id)
    return reports


@router.delete("/canaries/{canary_id}")
async def delete_canary(
    canary_id: str,
    current_user: User = Depends(require_role(UserRole.admin)),
):
    """Remove a canary config."""
    for _agent_id, configs in _canary_configs.items():
        for i, config in enumerate(configs):
            if config.get("id") == canary_id:
                configs.pop(i)
                await emit_security_event(
                    SecurityEvent(
                        event_type=EventType.CANARY_DELETED,
                        severity=Severity.INFO,
                        outcome="success",
                        actor_id=str(current_user.id),
                        actor_email=current_user.email,
                        actor_role=current_user.role.value,
                        target_id=canary_id,
                        target_type="canary",
                    )
                )
                await audit(current_user, "admin.canaries.delete", "canary", resource_id=canary_id)
                return {"deleted": canary_id}
    raise HTTPException(status_code=404, detail="Canary config not found")


# ── Security Audit Log ──────────────────────────────────


@router.get("/security-events")
async def get_security_events(
    event_type: str | None = None,
    severity: str | None = None,
    actor_email: str | None = None,
    limit: int = 100,
    offset: int = 0,
    current_user: User = Depends(require_role(UserRole.admin)),
):
    """Query the security events audit log from ClickHouse."""
    from services.clickhouse import _query

    conditions = ["1 = 1"]
    params: dict[str, str] = {}
    if event_type:
        conditions.append("event_type = {et:String}")
        params["param_et"] = event_type
    if severity:
        conditions.append("severity = {sev:String}")
        params["param_sev"] = severity
    if actor_email:
        conditions.append("actor_email = {ae:String}")
        params["param_ae"] = actor_email

    where = " AND ".join(conditions)
    limit = min(max(int(limit), 1), 1000)
    offset = max(int(offset), 0)
    sql = (
        f"SELECT * FROM security_events WHERE {where} ORDER BY timestamp DESC LIMIT {limit} OFFSET {offset} FORMAT JSON"
    )
    try:
        r = await _query(sql, params)
        r.raise_for_status()
        data = r.json()
        await audit(current_user, "admin.audit_log.view", "audit_log")
        return {"events": data.get("data", []), "total": data.get("rows", 0)}
    except Exception as e:
        logger.warning("Audit log query failed: %s", e)
        await audit(current_user, "admin.audit_log.view", "audit_log", detail="query_failed")
        return {"events": [], "total": 0}


@router.post("/resources/apply")
async def apply_resources(
    current_user: User = Depends(require_role(UserRole.admin)),
    db: AsyncSession = Depends(get_db),
):
    """Re-apply resource tuning settings to ClickHouse without restart."""
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


# ── Trace Privacy ──────────────────────────────────────────


@router.get("/org/trace-privacy")
async def get_trace_privacy(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin)),
):
    """Get the trace privacy setting for the current user's organization."""
    if not current_user.org_id:
        await audit(current_user, "admin.trace_privacy.view", "trace_privacy")
        return {"trace_privacy": False}
    result = await db.execute(select(Organization).where(Organization.id == current_user.org_id))
    org = result.scalar_one_or_none()
    if not org:
        await audit(current_user, "admin.trace_privacy.view", "trace_privacy")
        return {"trace_privacy": False}
    await audit(current_user, "admin.trace_privacy.view", "trace_privacy", resource_id=str(org.id))
    return {"trace_privacy": org.trace_privacy}


@router.put("/org/trace-privacy")
async def set_trace_privacy(
    req: dict,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin)),
):
    """Toggle trace privacy for the current user's organization.

    When enabled, all roles below super-admin can only see their own
    traces.  Super-admins always retain full visibility.
    """
    enabled = bool(req.get("trace_privacy", False))

    if not current_user.org_id:
        raise HTTPException(status_code=400, detail="User has no organization")

    result = await db.execute(select(Organization).where(Organization.id == current_user.org_id))
    org = result.scalar_one_or_none()
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")

    org.trace_privacy = enabled
    await db.commit()
    await db.refresh(org)
    await emit_security_event(
        SecurityEvent(
            event_type=EventType.SETTING_CHANGED,
            severity=Severity.WARNING,
            outcome="success",
            actor_id=str(current_user.id),
            actor_email=current_user.email,
            actor_role=current_user.role.value,
            target_id=str(org.id),
            target_type="organization",
            detail=f"Trace privacy {'enabled' if enabled else 'disabled'}",
        )
    )
    await audit(
        current_user,
        "admin.trace_privacy.update",
        "trace_privacy",
        resource_id=str(org.id),
        detail=json.dumps({"enabled": enabled}),
    )
    return {"trace_privacy": org.trace_privacy}


# ── Registered Agents Only ─────────────────────────────────


@router.get("/org/registered-agents-only")
async def get_registered_agents_only(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.user)),
):
    """Get the registered-agents-only setting for the current user's organization."""
    if not current_user.org_id:
        await audit(current_user, "admin.registered_agents_only.view", "registered_agents_only")
        return {"registered_agents_only": False}
    result = await db.execute(select(Organization).where(Organization.id == current_user.org_id))
    org = result.scalar_one_or_none()
    if not org:
        await audit(current_user, "admin.registered_agents_only.view", "registered_agents_only")
        return {"registered_agents_only": False}
    await audit(current_user, "admin.registered_agents_only.view", "registered_agents_only", resource_id=str(org.id))
    return {"registered_agents_only": org.registered_agents_only}


@router.put("/org/registered-agents-only")
async def set_registered_agents_only(
    req: dict,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.super_admin)),
):
    """Toggle registered-agents-only mode for the current user's organization.

    When enabled, only registered (active) agents are traced.
    Unregistered agent telemetry is stored as metadata-only (no content).
    """
    enabled = bool(req.get("registered_agents_only", False))

    if not current_user.org_id:
        raise HTTPException(status_code=400, detail="User has no organization")

    result = await db.execute(select(Organization).where(Organization.id == current_user.org_id))
    org = result.scalar_one_or_none()
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")

    org.registered_agents_only = enabled
    await db.commit()
    await db.refresh(org)
    await emit_security_event(
        SecurityEvent(
            event_type=EventType.SETTING_CHANGED,
            severity=Severity.WARNING,
            outcome="success",
            actor_id=str(current_user.id),
            actor_email=current_user.email,
            actor_role=current_user.role.value,
            target_id=str(org.id),
            target_type="organization",
            detail=f"Registered-agents-only {'enabled' if enabled else 'disabled'}",
        )
    )
    await audit(
        current_user,
        "admin.registered_agents_only.update",
        "registered_agents_only",
        resource_id=str(org.id),
        detail=json.dumps({"enabled": enabled}),
    )
    # Invalidate registry cache so all server instances pick up the change immediately
    from services.agent_registry_cache import invalidate as invalidate_registry_cache

    await invalidate_registry_cache()
    return {"registered_agents_only": org.registered_agents_only}


@router.post("/cache/clear")
async def clear_cache(current_user: User = Depends(require_role(UserRole.admin))):
    """Clear all cached dashboard and OTEL responses."""
    from services.cache import invalidate_all

    deleted = await invalidate_all()
    await audit(current_user, "admin.cache.clear", "cache", detail=json.dumps({"cleared": deleted}))
    return {"cleared": deleted}
