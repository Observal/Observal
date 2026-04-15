import hashlib
import logging
import secrets
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import get_db, require_role
from config import settings
from models.enterprise_config import EnterpriseConfig
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
        # Check for common misconfigurations
        if settings.SECRET_KEY == "change-me-to-a-random-string":
            issues.append("SECRET_KEY is using default value")
        if not settings.OAUTH_CLIENT_ID:
            issues.append("OAUTH_CLIENT_ID is not set")
        if settings.FRONTEND_URL in ("http://localhost:3000", ""):
            issues.append("FRONTEND_URL is localhost")
        diag["checks"]["enterprise"] = {
            "status": "ok" if not issues else "misconfigured",
            "issues": issues,
        }
        if issues:
            diag["status"] = "degraded"

    return diag


# ── Enterprise Settings ──────────────────────────────────


@router.get("/settings", response_model=list[EnterpriseConfigResponse])
async def list_settings(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin)),
):
    result = await db.execute(select(EnterpriseConfig).order_by(EnterpriseConfig.key))
    return [EnterpriseConfigResponse.model_validate(c) for c in result.scalars().all()]


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
    return {"deleted": key}


# ── User Management ──────────────────────────────────────


@router.get("/users", response_model=list[UserAdminResponse])
async def list_users(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin)),
):
    result = await db.execute(select(User).order_by(User.created_at.desc()))
    return [UserAdminResponse.model_validate(u) for u in result.scalars().all()]


@router.post("/users", response_model=UserCreateResponse)
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

    password = req.password or await _generate_unique_password(db)

    user = User(email=req.email, name=req.name, role=role)
    user.set_password(password)
    db.add(user)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="Email already registered")
    await db.refresh(user)

    return UserCreateResponse(
        id=user.id,
        email=user.email,
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

    if user_id == current_user.id and new_role != UserRole.admin:
        raise HTTPException(status_code=400, detail="Cannot demote yourself")

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user.role = new_role
    await db.commit()
    await db.refresh(user)
    return UserAdminResponse.model_validate(user)


@router.put("/users/{user_id}/password")
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
    result = await db.execute(select(User).where(User.id == user_id))
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
    logger.warning("Admin %s reset password for user %s", current_user.email, user.email)

    resp: dict[str, str] = {"message": f"Password reset for {user.email}"}
    if req.generate:
        resp["generated_password"] = new_password
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

    result = await db.execute(select(User).where(User.id == user_id))
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
    await db.delete(user)
    await db.commit()


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
    return [
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
    from services.canary import CanaryConfig

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

    return {"id": config.id, "agent_id": agent_id, "canary_type": config.canary_type}


@router.get("/canaries/{agent_id}", response_model=list[dict])
async def list_canaries(
    agent_id: str,
    current_user: User = Depends(require_role(UserRole.admin)),
):
    """List canary configs for an agent."""
    return _canary_configs.get(agent_id, [])


@router.get("/canaries/{agent_id}/reports", response_model=list[dict])
async def list_canary_reports(
    agent_id: str,
    current_user: User = Depends(require_role(UserRole.admin)),
):
    """List canary reports with pass/fail stats."""
    return _canary_reports.get(agent_id, [])


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
                return {"deleted": canary_id}
    raise HTTPException(status_code=404, detail="Canary config not found")
