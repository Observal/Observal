# SPDX-FileCopyrightText: 2026 Subramania Raja <dhanpraja231@gmail.com>
# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
# SPDX-FileCopyrightText: 2026 Vishnu Muthiah <vishnu.muthiah04@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Telemetry status for JSONL session ingestion."""

from fastapi import APIRouter, Depends
from loguru import logger as optic

from api.deps import require_role
from models.user import User, UserRole
from schemas.telemetry import TelemetryStatusResponse
from services.clickhouse import query_recent_events

router = APIRouter(prefix="/api/v1/telemetry", tags=["telemetry"])


@router.get("/status", response_model=TelemetryStatusResponse)
async def telemetry_status(current_user: User = Depends(require_role(UserRole.admin))):
    optic.trace("user_id={}", current_user.id)
    counts = await query_recent_events(60)
    return TelemetryStatusResponse(
        tool_call_events=counts["tool_call_events"],
        agent_interaction_events=counts["agent_interaction_events"],
        status="ok",
    )
