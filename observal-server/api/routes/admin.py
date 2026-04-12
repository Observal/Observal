import hashlib
import secrets
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import get_current_user, get_db
from config import settings
from models.enterprise_config import EnterpriseConfig
from models.user import User, UserRole
from schemas.admin import (
    EnterpriseConfigResponse,
    EnterpriseConfigUpdate,
    UserAdminResponse,
    UserCreateRequest,
    UserCreateResponse,
    UserRoleUpdate,
)

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])


def _require_admin(user: User):
    if user.role != UserRole.admin:
        raise HTTPException(status_code=403, detail="Admin access required")


# ── Enterprise Settings ──────────────────────────────────


@router.get("/settings", response_model=list[EnterpriseConfigResponse])
async def list_settings(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_admin(current_user)
    result = await db.execute(select(EnterpriseConfig).order_by(EnterpriseConfig.key))
    return [EnterpriseConfigResponse.model_validate(c) for c in result.scalars().all()]


@router.get("/settings/{key}", response_model=EnterpriseConfigResponse)
async def get_setting(
    key: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_admin(current_user)
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
    current_user: User = Depends(get_current_user),
):
    _require_admin(current_user)
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
    current_user: User = Depends(get_current_user),
):
    _require_admin(current_user)
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
    current_user: User = Depends(get_current_user),
):
    _require_admin(current_user)
    result = await db.execute(select(User).order_by(User.created_at.desc()))
    return [UserAdminResponse.model_validate(u) for u in result.scalars().all()]


@router.post("/users", response_model=UserCreateResponse)
async def create_user(
    req: UserCreateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Admin creates a new user and gets back their API key."""
    _require_admin(current_user)

    existing = await db.execute(select(User).where(User.email == req.email))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Email already registered")

    try:
        role = UserRole(req.role)
    except ValueError:
        raise HTTPException(status_code=422, detail=f"Invalid role. Must be one of: {[r.value for r in UserRole]}")

    api_key = secrets.token_hex(settings.API_KEY_LENGTH)
    key_hash = hashlib.sha256(api_key.encode()).hexdigest()

    user = User(email=req.email, name=req.name, role=role, api_key_hash=key_hash)
    db.add(user)
    await db.commit()
    await db.refresh(user)

    return UserCreateResponse(
        id=user.id,
        email=user.email,
        name=user.name,
        role=user.role.value,
        api_key=api_key,
    )


@router.put("/users/{user_id}/role", response_model=UserAdminResponse)
async def update_user_role(
    user_id: uuid.UUID,
    req: UserRoleUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_admin(current_user)
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


# ── Penalty & Weight Customization ──────────────────────


@router.get("/penalties", response_model=list[dict])
async def list_penalties(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List all penalty definitions."""
    _require_admin(current_user)
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
    current_user: User = Depends(get_current_user),
):
    """Enable/disable or modify a penalty definition."""
    _require_admin(current_user)
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
    current_user: User = Depends(get_current_user),
):
    """List global dimension weights."""
    _require_admin(current_user)
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
    current_user: User = Depends(get_current_user),
):
    """Set global dimension weights. Body: {dimension: weight, ...}"""
    _require_admin(current_user)
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
    current_user: User = Depends(get_current_user),
):
    """Set per-agent dimension weights. Body: {dimension: weight, ...}"""
    _require_admin(current_user)
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
    current_user: User = Depends(get_current_user),
):
    """Create a canary configuration for an agent."""
    _require_admin(current_user)
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
    current_user: User = Depends(get_current_user),
):
    """List canary configs for an agent."""
    _require_admin(current_user)
    return _canary_configs.get(agent_id, [])


@router.get("/canaries/{agent_id}/reports", response_model=list[dict])
async def list_canary_reports(
    agent_id: str,
    current_user: User = Depends(get_current_user),
):
    """List canary reports with pass/fail stats."""
    _require_admin(current_user)
    return _canary_reports.get(agent_id, [])


@router.delete("/canaries/{canary_id}")
async def delete_canary(
    canary_id: str,
    current_user: User = Depends(get_current_user),
):
    """Remove a canary config."""
    _require_admin(current_user)
    for _agent_id, configs in _canary_configs.items():
        for i, config in enumerate(configs):
            if config.get("id") == canary_id:
                configs.pop(i)
                return {"deleted": canary_id}
    raise HTTPException(status_code=404, detail="Canary config not found")
