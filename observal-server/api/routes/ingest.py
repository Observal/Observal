# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Session JSONL ingest endpoint."""

from fastapi import APIRouter, Depends
from loguru import logger as optic
from pydantic import BaseModel

from api.deps import get_project_id, require_role
from models.user import User, UserRole

router = APIRouter(prefix="/api/v1/ingest", tags=["ingest"])


class SessionIngestRequest(BaseModel):
    session_id: str
    ide: str = "claude-code"
    agent_id: str | None = None
    agent_version: str | None = None
    layer_hash: str | None = None
    lines: list[str]  # Raw JSONL lines
    start_offset: int = 0
    hook_event: str = "UserPromptSubmit"
    # Sent on Stop for integrity check
    final: bool = False
    total_line_count: int | None = None
    total_offset: int | None = None
    # Kiro-specific: total credits consumed this session
    total_credits: float | None = None
    # Claude Code subagent attribution: set when this session is a subagent
    parent_session_id: str | None = None


class SessionIngestResponse(BaseModel):
    ingested: int
    skipped: int
    errors: int
    integrity_ok: bool | None = None  # Only set when final=True


@router.post("/session", response_model=SessionIngestResponse)
async def ingest_session(
    req: SessionIngestRequest,
    current_user: User = Depends(require_role(UserRole.user)),
):
    """Ingest raw JSONL transcript lines from an IDE session.

    Called by the session_push hook on each UserPromptSubmit and Stop event.
    Lines are stored as-is and classified server-side.
    """
    optic.trace("user_id={}", current_user.id)
    from services.session_ingest import check_session_integrity, ingest_session_lines

    user_id = str(current_user.id)
    project_id = get_project_id(current_user)

    optic.debug(
        "ingest request: session={}, ide={}, lines={}, offset={}, final={}",
        req.session_id,
        req.ide,
        len(req.lines),
        req.start_offset,
        req.final,
    )

    result = await ingest_session_lines(
        session_id=req.session_id,
        project_id=project_id,
        user_id=user_id,
        agent_id=req.agent_id,
        agent_version=req.agent_version,
        layer_hash=req.layer_hash,
        ide=req.ide,
        lines=req.lines,
        start_offset=req.start_offset,
        total_credits=req.total_credits,
        parent_session_id=req.parent_session_id,
    )

    integrity_ok = None
    if req.final and req.total_line_count is not None:
        integrity = await check_session_integrity(
            session_id=req.session_id,
            project_id=project_id,
            expected_line_count=req.total_line_count,
            expected_offset=req.total_offset or 0,
        )
        integrity_ok = integrity.ok
        if not integrity_ok:
            optic.warning(
                "session integrity check failed: session={}, expected={}, actual offset={}",
                req.session_id,
                req.total_line_count,
                req.total_offset,
            )

    # Notify WebSocket subscribers so the frontend gets instant turn updates.
    # Publish to both a session-specific channel (for detail viewers, O(1) fan-out)
    # and the global channel (for list viewers with debounced refresh).
    if result.ingested > 0:
        from services.redis import publish

        _payload = {
            "session_id": req.session_id,
            "event_name": "session_push",
        }
        await publish(f"sessions:{req.session_id}:updated", _payload)
        await publish("sessions:updated", _payload)

    optic.info(
        "session ingested: session={}, ingested={}, skipped={}, errors={}",
        req.session_id,
        result.ingested,
        result.skipped,
        result.errors,
    )

    return SessionIngestResponse(
        ingested=result.ingested,
        skipped=result.skipped,
        errors=result.errors,
        integrity_ok=integrity_ok,
    )
