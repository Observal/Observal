# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-FileCopyrightText: 2026 Kaushik Kumar <kaushikrjpm10@gmail.com>
# SPDX-FileCopyrightText: 2026 Lokesh Selvam <lokeshselvam7025@gmail.com>
# SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Strawberry GraphQL schema for live UI subscriptions."""

from collections.abc import AsyncGenerator

import jwt
import strawberry
import structlog
from starlette.requests import Request

from services.jwt_service import decode_access_token
from services.redis import subscribe

logger = structlog.get_logger(__name__)

_DEFAULT_PROJECT = "default"


@strawberry.type
class Query:
    @strawberry.field
    def health(self) -> str:
        return "ok"


@strawberry.type
class SessionEvent:
    session_id: str
    event_name: str


@strawberry.type
class ReviewEvent:
    listing_id: str
    action: str


@strawberry.type
class Subscription:
    @strawberry.subscription
    async def session_updated(self, session_id: str | None = None) -> AsyncGenerator[SessionEvent, None]:
        channel = f"sessions:{session_id}:updated" if session_id else "sessions:updated"
        async for data in subscribe(channel):
            sid = data.get("session_id", "")
            if not session_id or sid == session_id:
                yield SessionEvent(session_id=sid, event_name=data.get("event_name", ""))

    @strawberry.subscription
    async def review_updated(self, listing_id: str | None = None) -> AsyncGenerator[ReviewEvent, None]:
        channel = "reviews:updated"
        async for data in subscribe(channel):
            lid = data.get("listing_id", "")
            if listing_id and lid != listing_id:
                continue
            yield ReviewEvent(listing_id=lid, action=data.get("action", ""))


async def _resolve_user_context_from_request(request) -> dict:
    import uuid as _uuid

    from sqlalchemy import select

    from database import async_session
    from models.user import User

    default = {"project_id": _DEFAULT_PROJECT, "user_id": None, "user_role": None, "trace_privacy": False}

    auth: str | None = None
    if request is not None:
        auth = request.headers.get("authorization")
    if not auth or not auth.startswith("Bearer "):
        return default
    token = auth.removeprefix("Bearer ").strip()
    try:
        payload = decode_access_token(token)
    except jwt.InvalidTokenError:
        return default

    sub = payload.get("sub")
    if not sub:
        return default

    try:
        uid = _uuid.UUID(sub)
    except ValueError:
        return default

    try:
        from models.organization import Organization

        async with async_session() as session:
            result = await session.execute(
                select(User.org_id, User.role, Organization.trace_privacy)
                .outerjoin(Organization, User.org_id == Organization.id)
                .where(User.id == uid)
            )
            row = result.one_or_none()
            if not row:
                return default
            org_id, role, trace_privacy = row
            return {
                "project_id": str(org_id) if org_id else _DEFAULT_PROJECT,
                "user_id": str(uid),
                "user_role": role.value if role else None,
                "trace_privacy": bool(trace_privacy),
            }
    except Exception:
        logger.debug("Failed to resolve user context for GraphQL", exc_info=True)
        return default


def get_context(
    project_id: str = _DEFAULT_PROJECT,
    user_id: str | None = None,
    user_role: str | None = None,
    trace_privacy: bool = False,
) -> dict:
    return {
        "project_id": project_id,
        "user_id": user_id,
        "user_role": user_role,
        "trace_privacy": trace_privacy,
    }


async def get_context_dep(request: Request = None) -> dict:
    ctx = await _resolve_user_context_from_request(request)
    return get_context(**ctx)


schema = strawberry.Schema(query=Query, subscription=Subscription)
