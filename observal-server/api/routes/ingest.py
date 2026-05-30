# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Session JSONL ingest endpoint."""

from fastapi import APIRouter, Depends, Request
from loguru import logger as optic
from pydantic import BaseModel, Field, field_validator

from api.deps import get_project_id, require_role
from api.ratelimit import limiter
from models.user import User, UserRole
from schemas.telemetry import MAX_SHORT_STRING_LENGTH, MAX_TEXT_LENGTH

router = APIRouter(prefix="/api/v1/ingest", tags=["ingest"])

MAX_SESSION_LINES = 1000


class SessionIngestRequest(BaseModel):
    session_id: str = Field(..., max_length=MAX_SHORT_STRING_LENGTH)
    ide: str = Field("claude-code", max_length=MAX_SHORT_STRING_LENGTH)
    agent_id: str | None = Field(None, max_length=MAX_SHORT_STRING_LENGTH)
    agent_version: str | None = Field(None, max_length=MAX_SHORT_STRING_LENGTH)
    layer_hash: str | None = Field(None, max_length=MAX_SHORT_STRING_LENGTH)
    lines: list[str] = Field(..., max_length=MAX_SESSION_LINES)  # Raw JSONL lines
    start_offset: int = Field(0, ge=0)
    hook_event: str = Field("UserPromptSubmit", max_length=MAX_SHORT_STRING_LENGTH)
    # Sent on Stop for integrity check
    final: bool = False
    total_line_count: int | None = Field(None, ge=0)
    total_offset: int | None = Field(None, ge=0)
    # Kiro-specific: total credits consumed this session
    total_credits: float | None = Field(None, ge=0)
    # Claude Code subagent attribution: set when this session is a subagent
    parent_session_id: str | None = Field(None, max_length=MAX_SHORT_STRING_LENGTH)

    @field_validator("lines")
    @classmethod
    def lines_are_bounded(cls, value: list[str]) -> list[str]:
        for line in value:
            if len(line) > MAX_TEXT_LENGTH:
                raise ValueError(f"session lines must be at most {MAX_TEXT_LENGTH} characters")
        return value


class SessionIngestResponse(BaseModel):
    ingested: int
    skipped: int
    errors: int
    integrity_ok: bool | None = None  # Only set when final=True


@router.post("/session", response_model=SessionIngestResponse)
@limiter.limit("60/minute")
async def ingest_session(
    req: SessionIngestRequest,
    request: Request,
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
    # Fire-and-forget so a Redis blip never blocks the HTTP response to the CLI.
    if result.ingested > 0:
        import asyncio

        from services.redis import publish

        _payload = {
            "session_id": req.session_id,
            "event_name": "session_push",
        }
        asyncio.create_task(publish(f"sessions:{req.session_id}:updated", _payload))  # noqa: RUF006
        asyncio.create_task(publish("sessions:updated", _payload))  # noqa: RUF006

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
