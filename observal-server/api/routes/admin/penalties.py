# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Admin penalty, weight, and canary routes."""

import json
import uuid

from fastapi import Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import get_db, require_role
from models.user import User, UserRole
from services.audit_helpers import audit
from services.security_events import EventType, SecurityEvent, Severity, emit_security_event

from ._router import router


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
