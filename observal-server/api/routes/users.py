# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Shared user search endpoints."""

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import get_db, require_role
from models.user import User, UserRole
from services.user_search import search_users

router = APIRouter(prefix="/api/v1/users", tags=["users"])


class UserSearchResult(BaseModel):
    id: str
    email: str
    username: str | None = None
    name: str
    avatar_url: str | None = None
    role: str
    is_active: bool


@router.get("/search", response_model=list[UserSearchResult])
async def search_users_route(
    q: str = Query(..., min_length=2, max_length=255),
    limit: int = Query(10, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.user)),
):
    del current_user
    return [
        UserSearchResult(
            id=str(match.user.id),
            email=match.user.email,
            username=match.user.username,
            name=match.user.name,
            avatar_url=match.user.avatar_url,
            role=match.user.role.value,
            is_active=match.user.auth_provider != "deactivated",
        )
        for match in await search_users(db, q, limit=limit)
    ]
